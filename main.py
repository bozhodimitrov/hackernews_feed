import asyncio
import json
import re
import time
from collections import OrderedDict
from contextlib import contextmanager
from contextlib import suppress
from datetime import datetime
from functools import wraps

import aiohttp
from aiosseclient import aiosseclient
from colorama import Fore
from colorama import Style


FETCH_ATTEMPTS = 3
FETCH_RETRY_DELAY = 3

BASE_URL = 'https://hacker-news.firebaseio.com/v0'
STORIES_URL = f'{BASE_URL}/newstories.json'
ITEM_URL = f'{BASE_URL}/item'
WEB_ITEM_URL = 'https://news.ycombinator.com/item?id='
INVALID_MSG = f'\n\n{Style.NORMAL}{Fore.RED}{{}}{Style.RESET_ALL}\n\n'
ITEM_PATTERN = re.compile(
    r'"title"><a href="(?P<url>.*?)".*?>(?P<title>.*?)</a>',
)

HEADERS = {'Accept': 'application/json'}
FIREBASE_TIMEOUT = 30 + 5
SSE_TIMEOUT = aiohttp.ClientTimeout(
    total=None,
    connect=FIREBASE_TIMEOUT,
    sock_connect=FIREBASE_TIMEOUT,
    sock_read=FIREBASE_TIMEOUT,
)


class LRU(OrderedDict):
    def __init__(self, maxsize=128, *args, **kwds):
        self.maxsize = maxsize
        super().__init__(*args, **kwds)

    def __contains__(self, key):
        found = super().__contains__(key)
        if found:
            self.move_to_end(key)
        else:
            self[key] = None
        return found

    def __getitem__(self, key):
        self.move_to_end(key)
        return super().__getitem__(key)

    def __setitem__(self, key, value):
        if super().__contains__(key):
            self.move_to_end(key)
        else:
            super().__setitem__(key, value)
        if len(self) > self.maxsize:
            oldest = next(iter(self))
            del self[oldest]


def retry(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        for _ in range(FETCH_ATTEMPTS):
            result = await func(*args, **kwargs)
            if not result:
                await asyncio.sleep(FETCH_RETRY_DELAY)
            else:
                break

        return result

    return wrapper


@retry
async def api_fetch(story_id):
    url = f'{ITEM_URL}/{story_id}.json'
    async with aiohttp.ClientSession() as session:
        with suppress(aiohttp.client_exceptions.ClientConnectorError):
            async with session.get(url, headers=HEADERS) as resp:
                if resp.status == 200:
                    return await resp.json()


@retry
async def web_fetch(story_id, timestamp):
    url = f'{WEB_ITEM_URL}{story_id}'
    async with aiohttp.ClientSession() as session:
        with suppress(aiohttp.client_exceptions.ClientConnectorError):
            async with session.get(url, headers=HEADERS) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    match = ITEM_PATTERN.search(html)
                    if match:
                        return {
                            'id': story_id,
                            'url': match.group('url'),
                            'title': match.group('title'),
                            'time': timestamp,
                        }


@contextmanager
def fetcher():
    async def fetch(story_id, timestamp):
        if not getattr(fetch, 'enable', False):
            return

        story = await api_fetch(story_id)
        if story:
            return story

        story = await web_fetch(story_id, timestamp)
        if story:
            return story
        else:
            print(INVALID_MSG.format(story_id))

    yield fetch


async def announce(story):
    posted_at = datetime.fromtimestamp(int(story['time'])).strftime('%H:%M:%S')
    print(
        f'{Style.BRIGHT}{Fore.BLUE}{posted_at} '
        f'{Style.NORMAL}{Fore.CYAN}{story.get("title", "-")} '
        f'{Style.BRIGHT}{Fore.GREEN}{story["id"]}\n'
        f'{Style.RESET_ALL}{story.get("url", "-")}',
    )


def load_stories(event_data):
    stories = json.loads(event_data)
    if not stories:
        return
    else:
        stories = stories.get('data', [])
        stories.sort()
        yield from stories


async def hackernews_feed():
    cache = LRU(1024)
    with fetcher() as fetch:
        async for event in aiosseclient(STORIES_URL, timeout=SSE_TIMEOUT):
            for story_id in load_stories(event.data):
                if story_id in cache:
                    continue
                else:
                    story = await fetch(story_id, time.time())
                    if story:
                        yield story
            else:
                fetch.enable = True


async def main():
    while True:
        try:
            async for story in hackernews_feed():
                await announce(story)
        except (
                asyncio.TimeoutError,
                aiohttp.client_exceptions.ClientConnectorError,
        ):
            print(f'{time.strftime("%X")} Retrying ...')
            await asyncio.sleep(FIREBASE_TIMEOUT)


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
