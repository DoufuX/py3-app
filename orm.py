import logging  # logging用来记录日志信息

import aiomysql  # aiomysql为MYSQL数据库提供了异步IO的驱动
# 一旦使用了异步后，系统每一层都必须是异步，"开弓没有回头箭"

import asyncio

logging.basicConfig(level=logging.DEBUG)  # 设置显示信息级别为INFO级别，这样就会显示所有级别为INFO日志信息


# 创建连接池
async def create_pool(loop, **kw):  # 参数中的loop（eventLoop）协程放在eventLoop里面执行
    logging.info("create db connection pool...")
    global __pool  # 创建全局变量__pool
    __pool = await aiomysql.create_pool(
        host=kw.get('host', 'localhost'),  # kw作为一个dict，dict.get()表示如果key为'host'存在时返回 kw[dict],否则返回 'localhost' 下同
        port=kw.get('port', 3306),
        user=kw['user'],  # db,user和password都必须自己输入而不是用默认值，所以这里没有用到get方法
        password=kw['password'],
        db=kw['db'],
        charset=kw.get('charset', 'utf8'),
        autocommit=kw.get('autocommit', True),
        loop=loop
    )


# 定义select操作
async def select(sql, args, size=None):
    logging.info(sql)
    logging.info(args)
    global __pool
    with (await __pool) as conn:
        cur = await conn.cursor(aiomysql.DictCursor)  # 开启游标，通过游标对数据库进行操作

        await cur.execute(sql.replace('?', '%s'), args or ())  # 这里or的用法：如果第一个判断条件非负，则返回第一个判断条件内容，否则返回第二个判断条件内容
        # execute是具体的对数据库进行操作的函数
        if size:
            rs = await cur.fetchmany(size)
        else:
            rs = await cur.fetchall()
        await cur.close()  # 关闭游标
        logging.info('rows return : %s' % len(rs))
        return rs


# 定义execute操作，包括insert，delate，update
async def execute(sql, args, autocommit=True):
    logging.info(sql.replace('?', '%s'))
    with (await __pool) as conn:
        # autocommit是看了别人的代码添加上去的，具体用途大概是定义是否自动commit（不过好像这里并不需要用到commit就会自动执行相应操作
        if not autocommit:
            await conn.begin()
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                logging.info(args)
                await cur.execute(sql.replace('?', '%s'), args)
                affected = cur.rowcount
            if not autocommit:
                await conn.commit()
        except BaseException as e:
            if not autocommit:
                await conn.rollback()
            raise
        # 添加上finally，不然会出现Event loop is closed 错误退出
        finally:
            conn.close()
        return affected


# 有多少个列就创建多少个'？'，用来执行insert操作时候用到
def create_args_string(num):
    L = []
    for n in range(num):
        L.append('?')
    return ', '.join(L)


# Metaclass部分
class ModelMetaclass(type):
    def __new__(cls, name, bases, attrs):
        #  cls：元类本身，name：类的名字， bases：类继承的类， attrs：类的相关属性（字典形式）

        #  Model通过ModelMetaclass创建，而我们用到的具体的表对应的类则是继承Model，这样我们创建的类也是由ModelMetaclass创建了
        if name == 'Model':
            return type.__new__(cls, name, bases, attrs)

        tableName = attrs.get('__table__', None) or name

        logging.info('found model: %s (table:%s)' % (name, tableName))
        # 如果在类中有明确定义__table__='xxxx',那么tableName即为这个值；否则tableName就为name，是类的名字
        # ------------------------------#

        mappings = dict()
        # mappings，用来存储表中相应列名（name）与具体列属性（Field）的对应关系
        fields = []
        # fields，用来存储表中除了primaryKey之外的列（表示列的类中有默认值，数据类型这些属性
        primaryKey = None
        for k, v in attrs.items():
            if isinstance(v, Field):
                logging.info(' found mapping: %s ==> %s' % (k, v))
                mappings[k] = v
                if v.primary_key:
                    if primaryKey:
                        raise RuntimeError('Duplicate primary key for field:%s')
                    primaryKey = k
                # 如果表中元素的primary_key属性为true，即表明该列为ptimaryKey，一个表不能有多个primary_key,所以如果有的话就抛出异常
                else:
                    fields.append(k)
                    # 非primaryKey就把列的名字加入fields列表中
        if not primaryKey:
            raise RuntimeError('Primary key not found.')
        for k in mappings.keys():
            attrs.pop(k)  # 相应表列名及其列属性相关数据已经在mapping中记录了，所以要在attrs中pop出来以让实例不与表的列名冲突，不然列属性相关信息（Field类实例）会被覆盖掉
            # Eg：name = StringField（）后又执行了 name = 'lili' 后 StringField的信息就会被 'lili'覆盖掉了
            # 所以要先把 name = StringField（）这个键值对存在 字典mappings 中，这个过程如上几行代码所示

        escaped_fields = list(map(lambda f: '`%s`' % f, fields))  # 对所有fields加上'',eg:name --> 'name'
        attrs['__mappings__'] = mappings  # 保存列名和数据类型的映射关系
        attrs['__table__'] = tableName  # 表名
        attrs['__primary_key__'] = primaryKey  # 主键属性名
        attrs['__fields__'] = fields  # 除了主键外的列属性名

        # 构造默认的SELECT,INSERT,UPDATE和DELETE语句框架
        attrs['__select__'] = 'select `%s`, %s from `%s`' % (primaryKey, ', '.join(escaped_fields), tableName)
        attrs['__insert__'] = 'insert into `%s` (%s, `%s`) value (%s)' % (
            tableName, ','.join(escaped_fields), primaryKey,
            create_args_string(len(escaped_fields) + 1))  # 记得要加一，因为escaped——fields中不包含主键
        attrs['__update__'] = 'update `%s` set %s where `%s`=?' % (
            tableName, ','.join(map(lambda f: '`%s`=?' % (mappings.get(f).name or f), fields)), primaryKey)
        attrs['__delete__'] = 'delete from `%s` where `%s`=?' % (tableName, primaryKey)
        return type.__new__(cls, name, bases, attrs)


class Model(dict, metaclass=ModelMetaclass):
    def __init__(self, **kw):
        super(Model, self).__init__(**kw)

    # 这里__init__为什么要这么写还是有点疑问，不写__init__会有影响吗？对这块不太熟悉

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(r"'model' object has no attribute '%s'" % key)

    def __setattr__(self, key, value):
        self[key] = value

    def getValue(self, key):
        return getattr(self, key, None)

    # 获取列的值，没有的话就用默认值
    def getValueOrDefault(self, key):
        value = getattr(self, key, None)
        if value is None:
            field = self.__mappings__[key]

            if field.default is not None:
                # vlaue = field.default() if callable(field.default()) else field.default
                # 原来代码是上面这么写的，但是会出现field.default为null，no callable报错，所以换成了下面方式
                value = field.default
                logging.debug('using default vlaue for %s:%s' % (key, str(value)))
                setattr(self, key, value)
        # 如果对应列没有指定值就使用mappping字典中存的默认值
        return value

    @classmethod
    async def findAll(cls, where=None, args=None, **kw):
        logging.info('findall part')
        ' find objects by where clause. '
        sql = [cls.__select__]
        if where:
            sql.append('where')
            sql.append(where)
        if args is None:
            args = []
        orderBy = kw.get('orderBy', None)
        if orderBy:
            sql.append('order by')
            sql.append(orderBy)
        limit = kw.get('limit', None)
        if limit is not None:
            sql.append('limit')
            if isinstance(limit, int):
                sql.append('?')
                args.append(limit)
            elif isinstance(limit, tuple) and len(limit) == 2:
                sql.append('?, ?')
                args.extend(limit)
            else:
                raise ValueError('Invalid limit value: %s' % str(limit))
        rs = await select(' '.join(sql), args)
        return [cls(**r) for r in rs]

    @classmethod
    async def findNumber(cls, selectField, where=None, args=None):
        ' find number by select and where. '
        sql = ['select %s _num_ from `%s`' % (selectField, cls.__table__)]
        if where:
            sql.append('where')
            sql.append(where)
        rs = await select(' '.join(sql), args, 1)
        if len(rs) == 0:
            return None
        return rs[0]['_num_']

    # 定义保存到数据库的操作
    async def save(self):
        # args = list(map(self.getValueOrDefault, self.__fields__))
        args = []
        for key in self.__fields__:
            args.append((self.getValueOrDefault(key)))
        args.append(self.getValueOrDefault(self.__primary_key__))
        # 构造参数列表
        rows = await execute(self.__insert__, args)  # 把参数套进insert框架，并通过execute执行
        if rows != 1:
            logging.warn('failed to insert record: affected rows: %s' % rows)

    @classmethod  # 类方法的标记
    # 为什么这里用的是表示元类的cls而不是self？猜想：因为类方法的self 为创建类方法的元类，而元类一般用cls表示
    async def find(cls, pk):
        'find object by primary key'
        rs = await select('%s where `%s`=?' % (cls.__select__, cls.__primaryKey__), [pk], 1)
        if len(rs) == 0:
            return None
        return cls(**rs[0])


# Field在这表示一个列，其包含了列的各种属性
# name这个属性好像不怎么会用到，一般都是直接用列名了，所以name属性有没有问题似乎都不大
class Field(object):
    def __init__(self, name, column_type, primary_key, default):
        self.name = name
        self.column_type = column_type
        self.primary_key = primary_key
        self.default = default

    def __str__(self):
        return '<%s,%s,%s>' % (self.__class__.__name__, self.column_type, self.name)


# 下面是各种不同列数据类型的Field

class StringField(Field):
    def __init__(self, name=None, primary_key=False, default=None, ddl='varchar(100)'):
        super().__init__(name, ddl, primary_key, default)


class IntegerField(Field):
    def __init__(self, name=None, primary_key=False, default=0, ddl='bright'):
        super().__init__(name, ddl, primary_key, default)


class BooleanField(Field):
    def __init__(self, name=None, primary_key=False, default=False, ddl='boolean'):
        super().__init__(name, ddl, primary_key, default)


class FloatField(Field):
    def __init__(self, name=None, primary_key=False, default=0.0, ddl='real'):
        super().__init__(name, ddl, primary_key, default)


class TextField(Field):
    def __init__(self, name=None, primary_key=False, default=None, ddl='text'):
        super().__init__(name, ddl, primary_key, default)
