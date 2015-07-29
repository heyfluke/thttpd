#!/usr/bin/env python

from thttpd import MiddleWare

class FlvSpeedLimiterMiddleWare(MiddleWare):

    def __init__(self):
        self.SLEEP_TIME = 1
        self.SLEEP_BYTE_INTERVAL = 1024
        self.sock_data = {}
        self.last_sleep = {}

    def filter_output_data(self, sock, filename, data):
        import time
        if filename.find('.flv') < 0:
            print 'filename not contain .flv, so not sleep'
            return data
        if sock not in self.sock_data:
            self.sock_data[sock] = 0
            self.last_sleep[sock] = 0
        length = len(data)
        self.sock_data[sock] += length
        if self.last_sleep[sock] + self.SLEEP_BYTE_INTERVAL < self.sock_data[sock]:
            self.last_sleep[sock] = self.sock_data[sock]
            print 'sleep %ds for filename %s, current data bytes: %d' % (self.SLEEP_TIME, filename, self.sock_data[sock])
            time.sleep(self.SLEEP_TIME)
        return data

plugin_instance = FlvSpeedLimiterMiddleWare()