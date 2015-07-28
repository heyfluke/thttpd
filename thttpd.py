#!/usr/bin/env python
#-*- coding: utf8 -*-

'''
Threading Block-IO Server
'''

'''
ChangeLogs
2011/9/22 
已经支持简单的http服务，支持index.html，支持列目录
'''

import sys, os, threading, socket, select, time, logging

G = {}
G['port'] = 9999
G['log_file_path'] = './thttpd.log'

## 通用部分

# 产生GMT时间，格式默认和HTTP返回时间一样
def strfGMTime(timestamp = time.time(), format = "%a, %d %b %Y %H:%M:%S"):
    time_tuple = time.gmtime(timestamp)
    return time.strftime(format, time_tuple)

# 产生本地时间
def strfLocalTime(timestamp = time.time(), format = "%a, %d %b %Y %H:%M:%S"):
    time_tuple = time.localtime(timestamp)
    return time.strftime(format, time_tuple)

# 产生目录html
def walktree(top = ".", depthfirst = True):
    """Walk the directory tree, starting from top. Credit to Noah Spurrier and Doug Fort."""
    import os, stat, types
    names = os.listdir(top)
    if not depthfirst:
        yield top, names
    for name in names:
        try:
            st = os.lstat(os.path.join(top, name))
        except os.error:
            continue
        if stat.S_ISDIR(st.st_mode):
            for (newtop, children) in walktree (os.path.join(top, name), depthfirst):
                yield newtop, children
    if depthfirst:
        yield top, names

def makeHTMLtable(top, depthfirst=False):
    from xml.sax.saxutils import escape # To quote out things like &amp;
    ret = ['<table class="fileList">\n']
    mark=0
    for top, names in walktree(top):
        #ret.append('   <tr><td class="directory">%s</td></tr>\n'%escape(top))
        for name in names:
            try:
              ext=os.path.basename(name).split('.', 1)[1]            
              if ext=='html' or ext=='htm':
                  ret.append('   <tr><td class="file"><a href="%s/%s">%s%s</a></td></tr>\n'%(escape(top),escape(name),escape(top),escape(name)))
                  mark=1                
            except IndexError:
                  pass
    ret.append('</table>')
    if mark ==1:
       return ''.join(ret) # Much faster than += method
    else:
       return ''
 
def makeHTMLpage(top, depthfirst=False):
    return '\n'.join(['<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN"',
                      '"http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">',
                      '<html>'
                      '<head>',
                      '   <title>Search results</title>',
                      '   <style type="text/css">',
                      '      table.fileList { text-align: left; }',
                      '      td.directory { font-weight: bold; }',
                      '      td.file { padding-left: 4em; }',
                      '   </style>',
                      '</head>',
                      '<body>',
                      '<h1>Search Results</h1>',
                      makeHTMLtable(top, depthfirst),
                      '</body>',
                      '</html>'])

# 日志模块
'''
def getLogger():
    global G

    logger = logging.getLogger()
    hdlr = logging.FileHandler(G['log_file_path'])
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
    hdlr.setFormatter(formatter)
    logger.addHandler(hdlr)
    logger.setLevel(logging.NOTSET)
 
    return logger
'''
def getLogger():
    class SimpleLogger:
        def __init__(self, logfile_path):
            self.fd = open(logfile_path, 'a')
            self.timeformat = '%a, %d %b %Y %H:%M:%S'

        def __del__(self):
            self.fd.close()

        def error(self, msg):
            return self.append(msg, 'ERROR')

        def info(self, msg):
            return self.append(msg, 'INFO')

        def warn(self, msg):
            return self.append(msg, 'WARN')

        def debug(self, msg):
            return self.append(msg, 'DEBUG')

        def append(self, msg, level='DEBUG'):
            timestr = strfLocalTime(time.time(), format = self.timeformat)
            self.fd.write('%s %s %s\n' % (timestr, level, msg))
    logger = SimpleLogger(G['log_file_path'])
    return logger



############################

class ServThread(threading.Thread):
    def __init__(self, clisock, threadno):
        threading.Thread.__init__(self)
        self.threadno = threadno
        self.clisock = clisock
        self.disconnected = False
        self._buffer = ''
        self._request_path = ''
        self._doc_root = './'
        self._range_start = 0
        self._range_end = 0

        self.get_conn_time = 0       # 练级开始的时间
        self.send_file_start = 0     # 开始发送文件的时间
        self.close_time = 0          # 连接被关闭的时间
        self.download_speed = 0

        self.unique_id = ''   # 客户端传来的 ? querystring
        
        self.delimiter = '\r\n'
        self.MAX_LINE_LENGTH = 1024
        
    def run(self):
        self.get_conn_time = time.time()
        msg = 'start handle the connection %lf' % (self.get_conn_time)
        self.doLog(msg)

        while True:
            if self.disconnected:
                break
            buf = self.clisock.recv(1024)
            if len(buf) == 0:
                break
            self.dataReceived(buf)
    
    def doLog(self, msg, bCritical=False):
        global logger
        if self.unique_id == '':
            if bCritical:
                logger.error('Thread #%d: %s' %(self.threadno, msg))
            else:
                logger.info('Thread #%d: %s' %(self.threadno, msg))
        else:
            if bCritical:
                logger.error('Thread #%d: [%s]%s' %(self.threadno, self.unique_id, msg))
            else:
                logger.info('Thread #%d: [%s]%s' %(self.threadno, self.unique_id, msg))
    
    # 断开连接
    def loseConnection(self):
        if self.disconnected:
            return
        else:
            self.clisock.close()
            self.disconnected = True

    # 发送一行
    def sendLine(self, data):
        self.clisock.send(data + self.delimiter)
    
    # 受到数据
    def dataReceived(self, data):
        lines  = (self._buffer+data).split(self.delimiter)
        self._buffer = lines.pop(-1)
        if len(lines):
            print 'lines: ', len(lines)
            for line in lines:
                if self.disconnected:
                    return
                if len(line) > self.MAX_LINE_LENGTH:
                    return self.lineLengthExceeded(line)
                else:
                    self.lineReceived(line)
    
    # 接收到一行的数据
    def lineReceived(self, line):
        #print ("." + line.decode('utf-8'))
        if line == '':   #
            '''
            if self._request_path == '/':
                self.sendLine('HTTP/1.1 200 OK')
                self.sendLine('Content-Length: %d' % (len('Hello World\n')))
                self.sendLine('')
                self.sendLine('Hello World\n')
                self.loseConnection()
            el
            '''
            if self._request_path == '/thttpd.py' or self._request_path == '/thttpd.pyc':
                self.sendLine('HTTP/1.1 403 Forbidden')
                self.sendLine('Content-Length: 1')
                self.sendLine('')
                self.sendLine('\n')
                self.loseConnection()
            else:
                self._request_path = ''.join([self._doc_root, self._request_path])
                print 'request_file', self._request_path
                #time.sleep(200) # make timeout
                self.sendFile(self._request_path, self._range_start, self._range_end)
        else:
            print ' >> ', line
            if line.find('GET') != -1:
                full_request_path = line.split()[1]
                path_split = full_request_path.split('?', 1)
                if len(path_split) == 2:
                    self._request_path = path_split[0]
                    self.unique_id = path_split[1]
                else:
                    self._request_path = full_request_path
                print 'request_path', self._request_path
            elif line.find('POST') != -1:
                full_request_path = line.split()[1]
                path_split = full_request_path.split('?', 1)
                if len(path_split) == 2:
                    self._request_path = path_split[0]
                    self.unique_id = path_split[1]
                else:
                    self._request_path = full_request_path
                print 'request_path', self._request_path
            if line.find('Range') != -1:
                try:
                    r = line.split('=')[1].split('-')
                    if len(r) >= 1 and r[0] != '':
                        self._range_start = int(r[0])
                    if len(r) >= 2 and r[1] != '':
                        self._range_end = int(r[1])
                except Exception, e:
                    print 'Exception while getting range:', e

    def sendFile(self, file_path, range_start=0, range_end=0):
        self.send_file_start = time.time()
        timestr = strfLocalTime(self.send_file_start)
        msg = 'thread %d send file start time %lf (%s)' % (self.threadno, self.send_file_start, timestr)
        self.doLog(msg)
        print msg
        file_size = 0
        content_length = 0
        bytes_remain = 0
        try:
            print 'file_path', file_path
            if file_path[-1] == '/': 
                print 'append index.html to', file_path
                
                if not os.path.isfile(file_path):
                    body = makeHTMLpage(file_path)
                    self.sendLine('HTTP/1.1 200 OK')
                    self.sendLine('Server: UltraHttpd/1.0')
                    self.sendLine('Content-Length: %d' % (len(body)))
                    self.sendLine('Connection: close')
                    self.sendLine('Content-Type: text/html')
                    self.sendLine('')
                    self.clisock.send(body)
                    return
                file_path += 'index.html'
        except Exception, e:
            print 'exception', e
        try:
            f = open(file_path, 'rb')
            f.seek(0, 2)
            file_size = f.tell()
            block_size = 8192
            bytes_pos = 0
            f.seek(range_start)

            if file_size == range_end:  # 相当于没结尾
                range_end = 0

            # TODO: 判断range的合法性
            if range_end == 0:  # 到结束
                content_length = file_size - range_start
                if range_start != 0:
                    self.sendLine('HTTP/1.1 206 Partial Content')
                else:
                    self.sendLine('HTTP/1.1 200 OK')
                self.sendLine('Server: UltraHttpd/1.0')
                self.sendLine('Accept-Ranges: bytes')
                self.sendLine('Content-Range: bytes %d-%d/%d' % (range_start, file_size-1, file_size))
                self.sendLine('Content-Length: %d' % (content_length))
                self.sendLine('Connection: close')
                self.sendLine('Content-Type: text/html')
                self.sendLine('')
                #print dir(self.transport)
                while bytes_pos < file_size:
                    self.clisock.send(f.read(block_size))
                    #print 'send1'
                    bytes_pos = f.tell()
                print 'send end'
            elif range_end != 0:    # 到中间
                real_range_end = (file_size-1 > range_end) and range_end or file_size-1
                content_length = real_range_end - range_start + 1
                print 'real_range_end', real_range_end
                self.sendLine('HTTP/1.1 206 Partial Content')   # TODO: 查看是否range满足文件大小的时候不需要发送206
                self.sendLine('Server: UltraHttpd/1.0')
                self.sendLine('Accept-Ranges: bytes')
                self.sendLine('Content-Range: bytes %d-%d/%d' % (range_start, real_range_end, file_size))
                self.sendLine('Content-Length: %d' % (content_length))
                self.sendLine('Connection: close')
                self.sendLine('Content-Type: text/plain')
                self.sendLine('')
                
                while bytes_pos < real_range_end:
                    #print 'bytes_pos %d, real_range_end %d' % (bytes_pos, real_range_end)
                    bytes_remain = real_range_end - bytes_pos + 1
                    read_size = (block_size < bytes_remain) and block_size or bytes_remain
                    #print 'read_size %d' % (read_size)
                    buf = f.read(read_size)
                    #print 'buf', buf
                    self.clisock.send(buf)
                    bytes_pos = f.tell()
                    #print 'send2', bytes_pos, hex(ord(buf[-1]))
                print 'send end'
            f.close()
        except socket.error, e:
            msg = 'exception', e, 'connection corrupt'
            print msg
            self.doLog(msg)
            self.close_time = time.time()
            self.download_speed = (content_length-bytes_remain)/(self.close_time - self.send_file_start) # dont count the payload
            msg = 'end time %lf, speed %lfKbyte(time: %lf)'  % (time.time(), 
                self.download_speed/1024, self.close_time - self.send_file_start)
            print msg
            self.doLog(msg)
            return
        except IOError, e:
            msg = 'exception', e, 'IOError, send not found'
            print msg
            self.doLog(msg)
            self.sendNotFound(file_path)
            self.loseConnection()
            return
        
        print 'wait for client close'
        #print dir(self.transport)
        #print help(self.transport.connectionLost)

        while True:
            rlist, wlist, elist = select.select([self.clisock], [], [], 30)
            if (rlist, wlist, elist) == ([], [], []):
                print 'wait timeout'
                print 'lose it'
                self.loseConnection()
                msg = 'client do not close the connection, the download speed is not guaranteed to be correct'
                break
            else:
                #print 'rlist', rlist
                #print 'wlist', wlist
                #print 'elist', elist
                if len(rlist) > 0:
                    print 'get rlist, break'
                    print 'lose it'
                    self.loseConnection()
                    msg = 'client close the connection, time is'
                    break
        self.doLog(msg)
        self.close_time = time.time()
        timestr = strfLocalTime(self.close_time)
        if self.close_time - self.send_file_start == 0: self.download_speed = content_length/1
        else: self.download_speed = content_length/(self.close_time - self.send_file_start) # dont count the payload
        msg = 'thread %d send file end time %lf(%s), speed %lfKbyte(time: %lf)'  % (self.threadno, time.time(), 
            timestr, self.download_speed/1024, self.close_time - self.send_file_start)
        print msg
        self.doLog(msg)

    # 发送404, 无关闭链接操作
    def sendNotFound(self, path):
        try:
            self.sendLine('HTTP/1.1 404 Not Found')
            self.sendLine('Date: %s GMT' % ( strfGMTime() ))
            self.sendLine('Server: UltraHttpd/1.0')
            self.sendLine('Accept-Ranges: bytes')
            self.sendLine('Connection: close')
            self.sendLine('Content-Type: text/plain')
            self.sendLine('Expires: %s GMT' % (strfGMTime()))
            self.sendLine('')
        except Exception, e:
            msg = 'maybe connection closed', e
            print msg
            self.doLog(msg)

    def lineLengthExceeded(self, line):
        print ("max line exceeded")
        self.lostConnection()

def MainLoop(port):
    servsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    servsock.bind(('', port))
    servsock.listen(1)
    threadno = 0
    try:
        while True:
            clisock, cliaddr = servsock.accept()
            print 'accept a connection from %s:%d, time %lf' % (cliaddr[0], cliaddr[1], time.time())
            threadno += 1
            work_thread = ServThread(clisock, threadno)
            work_thread.start()
            #print clisock.recv(720)
            #clisock.send('HTTP/1.1 200 OK\r\n')
            #clisock.send('Content-Length: %d' % (len('Hello World\n')))
            #clisock.send('\r\n')
            #clisock.send('Hello World\n')
            #clisock.close()
    except KeyboardInterrupt, e:
        print 'Keyboard Interrupt'
        try:
            servsock.close()
        except Exception,e:
            pass
        sys.exit(1)

if __name__ == '__main__':
    print 'Date:', strfGMTime(), 'GMT'
    logger = getLogger()
    import sys
    if len(sys.argv) > 1: G['port'] = int(sys.argv[1])
    print 'listening port:', G['port']
    MainLoop(G['port'])
