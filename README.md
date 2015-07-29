# 简单http服务器thttpd
## 用法
* 安装python
* ./thttp.py [端口] 或者 run9999.bat (windows)
* 默认会监听9999端口。
* 默认遍历他当前目录，支持子目录，支持文件传输

### 高级用法
* 在thttp.py里面修改MySleeperMiddleWare，这是一个限速的中间件，每个文件被发送到客户端的时候都会先流过这个中间件的filter_output_data函数，可以在这里sleep。

## TODO
* 自动识别文件的MIME
* 自动加载某个目录下面的所有中间件，这样就不用在主代码文件洗面修改了。