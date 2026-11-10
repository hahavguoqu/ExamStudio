"""Bounded reference retrieval; URLs and provenance come from the provider, never the LLM."""
import asyncio
import os
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx


async def search(query):
    async with httpx.AsyncClient(timeout=45) as client:
        for attempt in range(2):
            try:
                response = await client.post('https://api.deepseek.com/v1/tools/search',
                    headers={'Authorization': 'Bearer ' + os.environ.get('DEEPSEEK_API_KEY', '')},
                    json={'query': query[:128], 'count': 3, 'need_content': True})
                if response.status_code in (408, 429, 500, 502, 503, 504) and attempt == 0:
                    await asyncio.sleep(1)
                    continue
                if response.status_code != 200:
                    raise RuntimeError(f'参考资料检索暂不可用（HTTP {response.status_code}）')
                return response.json().get('results', [])
            except httpx.TransportError:
                if attempt:
                    raise RuntimeError('参考资料检索连接失败') from None
                await asyncio.sleep(1)


async def retrieve(inputs):
    if not inputs['search']:
        return [], ['本次未启用联网参考；不声明全网原创。']
    queries = []
    topic = ' '.join(filter(None, [inputs['grade'], inputs['topic'], inputs['model_name']]))
    queries.append(('参考题', topic + ' 数学题 ' + inputs['purpose']))
    if inputs['background'].strip():
        queries.append(('背景素材', inputs['background'] + ' 新闻 应用 ' + str(datetime.now().year)))
    refs, notes, seen = [], [], set()
    for category, query in queries:
        try:
            results = await search(query)
        except (RuntimeError, ValueError) as exc:
            notes.append(f'{category}：{exc}。可继续修改要求；未核实的事件不得作为事实。')
            continue
        for result in results:
            url = str(result.get('url', ''))
            parsed = urlparse(url)
            if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or url in seen:
                continue
            seen.add(url)
            content = str(result.get('content') or '')
            summary = str(result.get('summary') or result.get('snippet') or '')
            if not (content or summary):
                continue
            refs.append({'id': f'R{len(refs)+1}', 'category': category, 'title': str(result.get('title') or url),
                         'url': url, 'date': result.get('date'), 'retrieved_at': datetime.now(timezone.utc).isoformat(),
                         'query': query, 'content': (content or summary)[:10000],
                         'summary_only': not bool(content)})
        if not results:
            notes.append(f'{category}检索未找到结果。')
    return refs, notes
