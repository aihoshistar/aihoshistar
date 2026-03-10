import asyncio
import os
from typing import Dict, List, Optional, Set, Tuple, Union
import aiohttp

class Queries:
    def __init__(self, username: str, access_token: str, session: aiohttp.ClientSession, max_connections: int = 10):
        self.username = username
        self.access_token = access_token
        self.session = session
        self.semaphore = asyncio.Semaphore(max_connections)
        self.headers = {"Authorization": f"Bearer {self.access_token}"}

    async def query(self, generated_query: str) -> Dict:
        # requests fallback 제거하고 aiohttp 재시도 로직으로 변경
        async with self.semaphore:
            async with self.session.post("https://api.github.com/graphql", 
                                         headers=self.headers, 
                                         json={"query": generated_query}) as r:
                return await r.json()

    async def query_rest(self, path: str, params: Optional[Dict] = None) -> Dict:
        path = path.lstrip("/")
        headers = {"Authorization": f"token {self.access_token}"}
        
        for _ in range(3): # 재시도 횟수 조정
            async with self.semaphore:
                async with self.session.get(f"https://api.github.com/{path}", 
                                            headers=headers, params=params) as r:
                    if r.status == 202: # 아직 데이터 준비 중
                        await asyncio.sleep(2)
                        continue
                    if r.status != 200:
                        return {}
                    return await r.json()
        return {}

    # (... repos_overview, contrib_years 등 쿼리문 스태틱 메서드는 기존과 동일 ...)
    @staticmethod
    def repos_overview(contrib_cursor: Optional[str] = None, owned_cursor: Optional[str] = None) -> str:
        return f"""{{
  viewer {{
    login,
    name,
    repositories(
        first: 100,
        orderBy: {{ field: UPDATED_AT, direction: DESC }},
        isFork: false,
        after: {"null" if owned_cursor is None else '"'+ owned_cursor +'"'}
    ) {{
      pageInfo {{ hasNextPage, endCursor }}
      nodes {{
        nameWithOwner
        stargazers {{ totalCount }}
        forkCount
        languages(first: 10, orderBy: {{field: SIZE, direction: DESC}}) {{
          edges {{ size, node {{ name, color }} }}
        }}
      }}
    }}
    repositoriesContributedTo(
        first: 100,
        includeUserRepositories: false,
        orderBy: {{ field: UPDATED_AT, direction: DESC }},
        contributionTypes: [COMMIT, PULL_REQUEST, REPOSITORY, PULL_REQUEST_REVIEW]
        after: {"null" if contrib_cursor is None else '"'+ contrib_cursor +'"'}
    ) {{
      pageInfo {{ hasNextPage, endCursor }}
      nodes {{
        nameWithOwner
        stargazers {{ totalCount }}
        forkCount
        languages(first: 10, orderBy: {{field: SIZE, direction: DESC}}) {{
          edges {{ size, node {{ name, color }} }}
        }}
      }}
    }}
  }}
}}
"""

    @staticmethod
    def contrib_years() -> str:
        return "query { viewer { contributionsCollection { contributionYears } } }"

    @staticmethod
    def contribs_by_year(year: str) -> str:
        return f"""
    year{year}: contributionsCollection(from: "{year}-01-01T00:00:00Z", to: "{int(year) + 1}-01-01T00:00:00Z") {{
      contributionCalendar {{ totalContributions }}
    }}
"""

    @classmethod
    def all_contribs(cls, years: List[str]) -> str:
        by_years = "\n".join(map(cls.contribs_by_year, years))
        return f"query {{ viewer {{ {by_years} }} }}"

class Stats:
    def __init__(self, username: str, access_token: str, session: aiohttp.ClientSession,
                 exclude_repos: Optional[Set] = None, exclude_langs: Optional[Set] = None,
                 consider_forked_repos: bool = False):
        self.username = username
        self._exclude_repos = exclude_repos or set()
        self._exclude_langs = exclude_langs or set()
        self._consider_forked_repos = consider_forked_repos
        self.queries = Queries(username, access_token, session)

        self._name = None
        self._stargazers = None
        self._forks = None
        self._total_contributions = None
        self._languages = None
        self._repos = None
        self._ignored_repos = None
        self._lines_changed = None
        self._views = None

    async def get_stats(self) -> None:
        if self._stargazers is not None: return # 이미 로드됨

        self._stargazers, self._forks = 0, 0
        self._languages, self._repos, self._ignored_repos = {}, set(), set()
        
        next_owned, next_contrib = None, None
        while True:
            res = await self.queries.query(Queries.repos_overview(owned_cursor=next_owned, contrib_cursor=next_contrib))
            data = res.get("data", {}).get("viewer", {})
            if not data: break

            self._name = data.get("name") or data.get("login") or "No Name"
            
            owned = data.get("repositories", {})
            contrib = data.get("repositoriesContributedTo", {})
            
            target_repos = owned.get("nodes", [])
            if self._consider_forked_repos:
                target_repos += contrib.get("nodes", [])
            else:
                for r in contrib.get("nodes", []):
                    self._ignored_repos.add(r.get("nameWithOwner"))

            for repo in target_repos:
                name = repo.get("nameWithOwner")
                if name in self._repos or name in self._exclude_repos: continue
                
                self._repos.add(name)
                self._stargazers += repo.get("stargazers", {}).get("totalCount", 0)
                self._forks += repo.get("forkCount", 0)

                for lang in repo.get("languages", {}).get("edges", []):
                    lname = lang.get("node", {}).get("name", "Other")
                    if lname in self._exclude_langs: continue
                    
                    if lname not in self._languages:
                        self._languages[lname] = {"size": 0, "occurrences": 0, "color": lang.get("node", {}).get("color")}
                    self._languages[lname]["size"] += lang.get("size", 0)
                    self._languages[lname]["occurrences"] += 1

            if owned.get("pageInfo", {}).get("hasNextPage") or contrib.get("pageInfo", {}).get("hasNextPage"):
                next_owned = owned.get("pageInfo", {}).get("endCursor")
                next_contrib = contrib.get("pageInfo", {}).get("endCursor")
            else:
                break

        total_size = sum(v["size"] for v in self._languages.values()) or 1
        for v in self._languages.values():
            v["prop"] = (v["size"] / total_size) * 100

    @property
    async def name(self) -> str:
        await self.get_stats(); return self._name
    @property
    async def stargazers(self) -> int:
        await self.get_stats(); return self._stargazers
    @property
    async def forks(self) -> int:
        await self.get_stats(); return self._forks
    @property
    async def languages(self) -> Dict:
        await self.get_stats(); return self._languages
    @property
    async def all_repos(self) -> Set[str]:
        await self.get_stats(); return (self._repos | self._ignored_repos)

    @property
    async def total_contributions(self) -> int:
        if self._total_contributions is not None: return self._total_contributions
        res = await self.queries.query(Queries.contrib_years())
        years = res.get("data", {}).get("viewer", {}).get("contributionsCollection", {}).get("contributionYears", [])
        
        res_all = await self.queries.query(Queries.all_contribs(years))
        yearly_data = res_all.get("data", {}).get("viewer", {}).values()
        self._total_contributions = sum(y.get("contributionCalendar", {}).get("totalContributions", 0) for y in yearly_data)
        return self._total_contributions

    @property
    async def lines_changed(self) -> Tuple[int, int]:
        if self._lines_changed is not None: return self._lines_changed
        add, delt = 0, 0
        # 이 부분은 레포가 많으면 시간이 걸리므로 gather 고려 가능
        for repo in await self.all_repos:
            r = await self.queries.query_rest(f"repos/{repo}/stats/contributors")
            if not isinstance(r, list): continue
            for author_obj in r:
                if author_obj.get("author", {}).get("login") == self.username:
                    for week in author_obj.get("weeks", []):
                        add += week.get("a", 0)
                        delt += week.get("d", 0)
        self._lines_changed = (add, delt)
        return self._lines_changed

    @property
    async def views(self) -> int:
        if self._views is not None: return self._views
        # 트래픽 API는 권한이 있는 레포만 가능함
        tasks = [self.queries.query_rest(f"repos/{repo}/traffic/views") for repo in await self.all_repos]
        results = await asyncio.gather(*tasks)
        self._views = sum(sum(v.get("count", 0) for v in r.get("views", [])) for r in results if isinstance(r, dict))
        return self._views