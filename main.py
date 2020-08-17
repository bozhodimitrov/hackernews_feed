import json
import asyncio
import aiohttp
from contextlib import suppress
from datetime import datetime
from aiosseclient import aiosseclient
from colorama import Fore, Back, Style


FETCH_ATTEMPTS = 3
FETCH_RETRY_DELAY = 5
BASE_URL = 'https://hacker-news.firebaseio.com/v0'
STORIES_URL = f'{BASE_URL}/newstories.json'
ITEM_URL = f'{BASE_URL}/item'
HEADERS = { 'Accept': 'application/json' }
SSE_TIMEOUT = aiohttp.ClientTimeout(
    total=None, connect=None, sock_connect=None, sock_read=None
)
INVALID_START = f'\n\n{Style.NORMAL}{Fore.RED}'
INVALID_END = f'{Style.RESET_ALL}\n\n'


async def fetch_story(story_id):
    url = f'{ITEM_URL}/{story_id}.json'
    async with aiohttp.ClientSession() as session:
        for _ in range(FETCH_ATTEMPTS):
            with suppress(aiohttp.client_exceptions.ClientConnectorError):
                async with session.get(url, headers=HEADERS) as resp:
                        if resp.status != 200:
                            print(f'{resp.status} error')
                            return

                        result = await resp.json()
                        if result != None:
                            return result
                
            await asyncio.sleep(FETCH_RETRY_DELAY)


async def announce(story):
    if not hasattr(announce, 'enable') or not announce.enable:
        return

    posted_at = datetime.fromtimestamp(int(story['time'])).strftime('%H:%M:%S')
    print(
        f'{Style.BRIGHT}{Fore.BLUE}{posted_at} '
        f'{Style.NORMAL}{Fore.CYAN}{story.get("title", "-")} '
        f'{Style.BRIGHT}{Fore.GREEN}{story["id"]}\n'
        f'{Style.RESET_ALL}{story.get("url", "-")}'
    )


async def hackernews_feed():
    max_story_id = 0
    while True:
        async for event in aiosseclient(STORIES_URL, timeout=SSE_TIMEOUT):
            stories = json.loads(event.data)
            if stories == None:
                continue

            stories = stories.get('data', [])
            for story_id in stories:
                if story_id <= max_story_id:
                    continue

                max_story_id = story_id
                story = await fetch_story(story_id)
                if story == None:
                    print(f'{INVALID_START}{story_id}{INVALID_END}')
                else:
                    yield story
            else:
                announce.enable = True


async def main():
    async for story in hackernews_feed():
        await announce(story)


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    with suppress(KeyboardInterrupt):
        loop.run_until_complete(main())
