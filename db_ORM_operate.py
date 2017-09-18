import asyncio
import logging

import orm
from models import User

# from web_app_v0 import loop


# class User(Model):
#     __table__ = 'users'
#
#     id = IntegerField(primary_key = True)
#     name = StringField
#
# user = User(id=123, name='Michael')
# user.insert()
# users = User.findAll()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

loop = asyncio.get_event_loop()  # 创建一个eventLoop，然后把协程丢进里面跑


async def test():
    await orm.create_pool(loop=loop, user='www-data', password='www-data', db='awesome')

    u2 = User(name='liufu', email='111222@333.com', admin=False, passwd='23456', image='about:blank')

    await u2.save()


loop.run_until_complete(test())
loop.close()
