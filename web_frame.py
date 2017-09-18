import asyncio
import os

import inspect
import logging
import functools

from urllib import parse

from aiohttp import web


# --------------get和post装饰器，用于增加__method__和__route__特殊属性，分别标记GET,POST方法和path

def get(path):
    '''
    Define decorator @get('/path')
    '''

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return (func(*args, **kwargs))

        # 装饰后添加__method__和__route__两个属性
        wrapper.__method__ = 'GET'
        wrapper.__route__ = path
        return wrapper

    return decorator


def post(path):
    '''
    Define decorator @post('/path')
    '''

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return (func(*args, **kwargs))

        wrapper.__method__ = 'POST'
        wrapper.__route__ = path
        return wrapper

    return decorator


# 提取没有默认值的命名关键字
# 下面的几个函数都是对传入的fn的参数中提取关键字参数（**）[named_kw_arg]和强制关键字参数（*，a)[required_kw_arg]
def get_required_kw_args(fn):
    args = []
    params = inspect.signature(fn).parameters  # 获取相应函数的参数内容,具体可以自己试试inspect.signature函数，返回的是一个mappingproxy（映射）类型对象
    for name, param in params.items():
        # 判断语句中后半句 param.default == inspect.Parameter.empty 判断参数默认值是否为空,如果参数形式为(*,a)则为true，为（*，a=1)这种则为False
        if param.kind == inspect.Parameter.KEYWORD_ONLY and param.default == inspect.Parameter.empty:
            args.append(name)
    return tuple(args)


# 如果url处理函数需要传入强制关键字参数 eg:(a,*,b)中的b就是KEYWORD_ONLY参数，获取该参数名称
def get_named_kw_args(fn):
    args = []
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY:
            args.append(name)
    return tuple(args)


# 判断是否有命名关键字参数
def has_named_kw_args(fn):
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY:
            return True


def has_var_kw_arg(fn):
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            return True


# 判断是否有名叫'request'的参数
def has_request_arg(fn):
    sig = inspect.signature(fn)
    params = sig.parameters
    found = False
    for name, param in params.items():
        if name == 'request':
            found = True
            continue

        if found and (
                            param.kind != inspect.Parameter.VAR_POSITIONAL and param.kind != inspect.Parameter.KEYWORD_ONLY and param.kind != inspect.Parameter.VAR_KEYWORD):
            raise ValueError(
                'request parameter must be the last named parameter in function: %s%s' % (fn.__name__, str(sig)))
    return found


# 用来封装一个URL处理函数
# 目的是从URL函数中分析其需要接受的参数，从request中获取必要的参数，调用URL函数
class RequestHandler(object):
    # 接受app参数
    def __init__(self, app, fn):
        self._app = app
        self._func = fn
        self._has_request_arg = has_request_arg(fn)
        self._has_var_kw_arg = has_var_kw_arg(fn)
        self._has_named_kw_args = has_named_kw_args(fn)
        self._named_kw_args = get_named_kw_args(fn)
        self._required_kw_args = get_required_kw_args(fn)

    @asyncio.coroutine
    def __call__(self, request):
        kw = None

        if self._has_var_kw_arg or self._has_named_kw_args or self._required_kw_args:

            if request.method == 'POST':  # 判断客户端发来的方法是否为POST
                if not request.content_type:  # 查询有没有提交数据的格式
                    return web.HTTPBadRequest(text='Missing Content-Type.')
                ct = request.content_type.lower()
                if ct.startswith('application/json'):
                    params = yield from request.json()  # 以json格式读取json文件  疑问点

                    if not isinstance(params, dict):
                        return web.HTTPBadRequest(text='JSON body must be object.')
                    kw = params

                elif ct.startswith('application/x-www-form-urlencoded') or ct.startswith('multipart/form-data'):
                    params = yield from request.post()  # 返回post参数 疑问点
                    kw = dict(**params)

                else:
                    return web.HTTPBadRequest(text='Unsupported Content type : %s' % request.content_type)

            if request.method == 'GET':  # 疑问点
                qs = request.query_string  # query_string就是诸如 'xxx.asp?pn=123456' 中的？后面的'pn=123456'
                if qs:
                    kw = dict()
                    for k, v in parse.parse_qs(qs, True).items():
                        kw[k] = v[0]

        # 不知道match info 是干嘛的
        if kw is None:
            kw = dict(**request.match_info)

        else:
            # 如果没有var_kw_arg (**) 但有 named_kw_args
            if not self._has_var_kw_arg and self._named_kw_args:
                copy = dict()
                for name in self._named_kw_args:
                    if name in kw:  # 个人猜测： kw是网页的request里生成的，而_name_kw_args是在request处理函数里提取的？
                        copy[name] = kw[name]
                kw = copy

            for k, v in request.match_info.items():  # 疑问点 还是不懂match_info是个什么鬼,所以下面也就不是很理解
                if k in kw:
                    logging.warning('Duplicate arg name in named arg and kw args: %s' % k)

                kw[k] = v

        if self._has_request_arg:
            kw['request'] = request

        if self._required_kw_args:
            for name in self._required_kw_args:
                if not name in kw:
                    return web.HTTPBadRequest(text='Missing argument:%s' % name)

        logging.info('call with args: %s' % str(kw))
        try:
            r = yield from self._func(**kw)
            return r
        except:
            pass


def add_static(app):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
    app.router.add_static('/static/', path)
    logging.info('add static %s => %s' % ('/static/', path))


def add_route(app, fn):
    method = getattr(fn, '__method__', None)
    path = getattr(fn, '__route__', None)
    if path is None or method is None:
        raise ValueError('@get or @post not defined in %s' % str(fn))
    if not asyncio.iscoroutine(fn) and not inspect.isgeneratorfunction(fn):
        fn = asyncio.coroutine(fn)
    logging.info('add route %s %s => %s (%s)' % (
        method, path, fn.__name__, ','.join(inspect.signature(fn).parameters.keys()))
                 )
    app.router.add_route(method, path, RequestHandler(app, fn))
    # app.router.add_route()中 method：方法，如'GET'，path：网页路径 如'/'， 第三个参数为返回的网页文本


def add_routes(app, module_name):
    n = module_name.rfind('.')
    logging.info('n=%s', n)

    if n == (-1):
        logging.info('module_name')
        logging.info(module_name)
        mod = __import__(module_name, globals(), locals())
        logging.info('global = %s', globals()['__name__'])
    else:
        logging.info('module_name')
        logging.info(module_name)
        name = module_name[n + 1:]
        mod = getattr(__import__(module_name[:n], globals(), locals(), [name]), name)
        # 上面两行是廖大大的源代码，但是把传入参数module_name的值改为'handlers.py'的话走这里是报错的，所以改成了下面这样
        # mod = __import__(module_name[:n], globals(), locals())
        # 这里不是很懂，为什么要 __import__ module_name[:n]???

    for attr in dir(mod):
        if attr.startswith('_'):
            continue
        fn = getattr(mod, attr)
        if callable(fn):
            method = getattr(fn, '__method__', None)
            path = getattr(fn, '__route__', None)
            if method and path:
                add_route(app, fn)
