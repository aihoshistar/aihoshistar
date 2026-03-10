import asyncio
import os
import re
import aiohttp
from github_stats import Stats

def generate_output_folder() -> None:
    # 이미 존재해도 에러가 나지 않도록 수정
    os.makedirs("generated", exist_ok=True)

async def generate_overview(s: Stats) -> None:
    """
    Generate an SVG badge with summary statistics
    """
    with open("templates/overview.svg", "r", encoding="utf-8") as f:
        output = f.read()

    # 데이터를 미리 await로 받아두고, None일 경우 기본값 처리
    name = await s.name or ""
    stars = await s.stargazers
    forks = await s.forks
    contribs = await s.total_contributions
    views = await s.views
    all_repos = await s.all_repos
    lines = await s.lines_changed
    changed = (lines[0] + lines[1]) if lines else 0

    # re.sub에 전달되는 값이 절대 None이 아니도록 보장
    output = re.sub("{{ name }}", str(name), output)
    output = re.sub("{{ stars }}", f"{stars or 0:,}", output)
    output = re.sub("{{ forks }}", f"{forks or 0:,}", output)
    output = re.sub("{{ contributions }}", f"{contribs or 0:,}", output)
    output = re.sub("{{ lines_changed }}", f"{changed:,}", output)
    output = re.sub("{{ views }}", f"{views or 0:,}", output)
    output = re.sub("{{ repos }}", f"{len(all_repos) if all_repos else 0:,}", output)

    generate_output_folder()
    with open("generated/overview.svg", "w", encoding="utf-8") as f:
        f.write(output)

async def generate_languages(s: Stats) -> None:
    try:
        with open("templates/languages.svg", "r", encoding="utf-8") as f:
            output = f.read()
    except FileNotFoundError:
        print("Error: templates/languages.svg not found.")
        return

    progress = ""
    lang_list = ""
    sorted_languages = sorted((await s.languages).items(), reverse=True, key=lambda t: t[1].get("size"))
    
    delay_between = 150
    for i, (lang, data) in enumerate(sorted_languages):
        color = data.get("color") or "#000000"
        prop = data.get("prop", 0)
        
        ratio = [0.99, 0.01] if prop > 50 else [0.98, 0.02]
        if i == len(sorted_languages) - 1: ratio = [1, 0]
        
        progress += (f'<span style="background-color: {color};'
                     f'width: {(ratio[0] * prop):0.3f}%;'
                     f'margin-right: {(ratio[1] * prop):0.3f}%;" '
                     f'class="progress-item"></span>')
        
        lang_list += f"""
<li style="animation-delay: {i * delay_between}ms;">
<svg xmlns="http://www.w3.org/2000/svg" class="octicon" style="fill:{color};"
viewBox="0 0 16 16" version="1.1" width="16" height="16"><path
fill-rule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8z"></path></svg>
<span class="lang">{lang}</span>
<span class="percent">{prop:0.2f}%</span>
</li>
"""

    output = re.sub(r"{{ progress }}", progress, output)
    output = re.sub(r"{{ lang_list }}", lang_list, output)

    generate_output_folder()
    with open("generated/languages.svg", "w", encoding="utf-8") as f:
        f.write(output)

async def main() -> None:
    # 토큰 체크 로직 간소화
    access_token = os.getenv("ACCESS_TOKEN") or os.getenv("GITHUB_TOKEN")
    if not access_token:
        raise ValueError("GITHUB_TOKEN or ACCESS_TOKEN is required")

    user = os.getenv("GITHUB_ACTOR")
    
    def parse_env_list(env_name):
        val = os.getenv(env_name)
        return {x.strip() for x in val.split(",")} if val else None

    async with aiohttp.ClientSession() as session:
        s = Stats(
            user, access_token, session, 
            exclude_repos=parse_env_list("EXCLUDED"),
            exclude_langs=parse_env_list("EXCLUDED_LANGS"),
            consider_forked_repos=bool(os.getenv("COUNT_STATS_FROM_FORKS"))
        )
        await asyncio.gather(generate_languages(s), generate_overview(s))

if __name__ == "__main__":
    asyncio.run(main())