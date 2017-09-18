from models import User

from web_frame import get
from aiohttp import web

import logging

logging.basicConfig(level=logging.INFO)


@get('/')
async def index(request):
    users = await User.findAll()
    logging.debug('handlers part')
    logging.info(users)
    return {
        '__template__': 'test.html',
        'users': users

    }  # 注意这里没有返回web.Response对象，将返回结果转换成Response对象需要依靠middleware


# @get('/')
# async def index(request):
#     return web.Response(body=b'<h1>Awesome python web app!</h1>', content_type='TEXT/HTML')