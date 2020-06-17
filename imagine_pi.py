#!/usr/bin/env python3
"""imagine_pi download and write official pi images to removable storage"""

###########
## Stdlib

import gzip
import hashlib
import itertools
import json
import lzma
import os
import re
import shlex
import subprocess
import sys
import time
import zipfile
from collections import namedtuple
from curses import wrapper
from urllib.parse import urlparse

import requests

####################
## Globals

__version__ = '0.3.dev'
PY3 = sys.version_info[0] == 3
string_types = str if PY3 else basestring # pylint: disable=undefined-variable
Response = namedtuple('Response', 'returncode value')

ENV = 'prd'


BUF_SIZE = 40960
OS_LIST_URL = "https://downloads.raspberrypi.org/os_list_imagingutility.json"
CACHE_PATH = '/var/tmp/imagine-pi'
CACHE_DOWNLOAD_PATH = CACHE_PATH + '/download'
CACHE_IMAGE_PATH = CACHE_PATH + '/images'
WHIPTAIL_HEIGHT = 20
WHIPTAIL_WIDTH = 80

####################
## Strings

STR_TITLE = 'Imagine PI'
STR_TITLE_SUB = 'raspberry pi imager for console'
STR_NO_ROOT = STR_TITLE + ' must be run as root!'
STR_SELECT_OS = 'Select OS to install'
STR_ABORT_OS_SELECTION = 'OS Selection aborted'
STR_NO_AVAILABLE_STORAGE = 'No storage devices without mounts available to image'
STR_SELECT_DEVICE = 'Select device to install os on'
STR_ABORT_DEVICE_SELECTION = 'Device Selection aborted'
STR_CONFIRM_INSTALL = 'Install\n - {0}\non device\n - {1}'
STR_ABORT_INSTALL = 'Imaging pi os aborted'
STR_SUMMARY = 'Installing\n - {0}\non device\n - {1}'
STR_IMG = 'image'
STR_IMG_ARCHIVE = 'image archive'
STR_EXTRACTING = 'extracting {0} from {1}'
STR_CHECKING_CACHE = 'checking cache'
STR_CACHE = 'cache'
STR_DOWNLOAD = 'download'
STR_DOWNLOADING = 'downloading {0}'
STR_AVAILABLE = '{0} available [{1}]'
STR_RETRIEVING = 'retrieving {0}'
STR_WRITING_IMG = 'writing {0} to {1}'
STR_IMG_INSTALLED = 'image {0} installed on {1}'
STR_SUCCESS = 'success!'

STR_BACKTITLE = '{0} - {1}'.format(STR_TITLE, STR_TITLE_SUB)
STR_HR = '-' * max(50, (len(STR_BACKTITLE) + 4))
STR_HEADER_PADDING = ' ' * (min(int((50-len(STR_BACKTITLE))/2), 2))

####################
## Utility classes

class HumanReadable:
    """convert machine data to human readable strings"""
    def __init__(self):
        pass

    def size(self, bit_size=0):
        try:
            filesize = float(bit_size)
            for count in ['Bytes', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB']:
                if filesize > -1024.0 and filesize < 1024.0:
                    return "      %3.1f %s" % (filesize, count)
                filesize /= 1024.0
        except Exception:
            return bit_size

    def time(self, seconds=0):
        minute = 60
        hour   = (minute**2)
        day    = (hour*24)
        week   = (day*7)
        month  = (week*4)
        year   = (month*12)

        secs, mins, hrs, days, weeks, months, years = 0, 0, 0, 0, 0, 0, 0

        if seconds > year:
            years   = (seconds / year)
            tmp     = (seconds % year)
            seconds = tmp
        if seconds > month:
            months  = (seconds / month)
            tmp     = (seconds % month)
            seconds = tmp
        if seconds > week:
            weeks   = (seconds / week)
            tmp     = (seconds % week)
            seconds = tmp
        if seconds > day:
            days    = (seconds / day)
            tmp     = (seconds % day)
            seconds = tmp
        if seconds > hour:
            hrs     = (seconds / hour)
            tmp     = (seconds % hour)
            seconds = tmp
        if seconds > minute:
            mins    = (seconds / minute)
            secs    = (seconds % minute)
        if seconds < minute:
            secs   = seconds

        if years != 0:
            return '%4dy%2dm%1dw%1dd %02d:%02d:%02d' % (
                years, months, weeks, days, hrs, mins, secs
            )
        if months != 0:
            return '%2dm%1dw%1dd %02d:%02d:%02d' % (
                months, weeks, days, hrs, mins, secs
            )
        if weeks != 0:
            return '%1dw%1dd %02d:%02d:%02d' % (
                weeks, days, hrs, mins, secs
            )
        if days != 0:
            return '%1dd %02d:%02d:%02d' % (days, hrs, mins, secs)

        return '%02d:%02d:%02d' % (hrs, mins, secs)

class Output(HumanReadable):
    """get and use display information"""
    def __init__(self):
        self.display_flag  = True
        self.display_count = None
        self.bar_fill = '█'
        self.bar_padding = ' '
        self.exit_string = None
        self._last_output = ''

        # This is the most portable way (across POSIX systems) to get
        # our screen size that I can find, so, screw windows. Yeah.
        if ENV == 'dev':
            self.max_x = 80
            self.max_y = 40
        else:
            wrapper(self.__setmaxyx)

    def __setmaxyx(self, stdscr):
        (self.max_y, self.max_x) = stdscr.getmaxyx()

    def display(self, inTot=None, inSz=None, outSz=None, start_time=None, prefix=''):
        try:
            a = self.lastupdate # pylint: disable=unused-variable
        except AttributeError:
            self.lastupdate = (time.time() - 5)

        if inTot:
            remain  = (inTot - outSz)
            percent = (float(outSz) / float(inTot))
            elapsed = (time.time() - start_time)
            speed   = (float(outSz) / float(elapsed))
            eta     = int(remain / speed)

            # now build out the majority of the display string
            linest  = '%s in %s @ %s/sec [' % (
                self.size(outSz),
                self.time(elapsed),
                self.size(speed)
            )
            lineend = '] %3d%% eta %s' % (
                int(percent * 100),
                self.time(eta)
            )

            # now figure out how many hashmarks we need
            curlen  = (len(prefix)+len(linest)+len(lineend))
            hashlen = (self.max_x - curlen)
            hashes  = int(hashlen * percent)
            padding = (hashlen - hashes)

            # and put the line together
            line    = '%s%s%s%s%s' % (
                prefix,
                linest,
                self.bar_fill*hashes,
                self.bar_padding*padding,
                lineend
            )

        else:
            line = '%s %s in %s @ %s/sec' % (
                prefix,
                self.size(outSz),
                self.time(time.time() - start_time),
                self.size((outSz / (time.time() - start_time)))
            )

        if (time.time() - self.lastupdate) >= 1 and not self.quiet: # pylint: disable=no-member
            sys.stderr.write('%s\r' % line)
            sys.stderr.flush()
            self._last_output = line
            self.lastupdate = time.time()

    def clear_display(self):
        sys.stderr.write('{0}\r'.format(" "*len(self._last_output)))
        sys.stderr.flush()
        self._last_output = ''

class Whiptail(object):
    """interact and build menus using whiptail in python"""
    """copyied code from web with GNU license (cannot find url)"""

    def __init__(self, title='', backtitle='', height=10, width=50,
                 auto_exit=True):
        self.title = title
        self.backtitle = backtitle
        self.height = height
        self.width = width
        self.auto_exit = auto_exit

    def run(self, control, msg, extra=(), exit_on=(1, 255)):
        cmd = [
            'whiptail', '--title', self.title, '--backtitle', self.backtitle,
            '--' + control, msg, str(self.height), str(self.width)
        ]
        cmd += list(extra)
        p = subprocess.Popen(cmd, stderr=subprocess.PIPE)
        out, err = p.communicate() # pylint: disable=unused-variable
        if self.auto_exit and p.returncode in exit_on:
            sys.exit(p.returncode)
        return Response(p.returncode, err)

    def prompt(self, msg, default='', password=False):
        control = 'passwordbox' if password else 'inputbox'
        return self.run(control, msg, [default]).value

    def confirm(self, msg, default='yes'):
        defaultno = '--defaultno' if default == 'no' else ''
        return self.run('yesno', msg, [defaultno], [255]).returncode == 0

    def alert(self, msg):
        self.run('msgbox', msg)

    def view_file(self, path):
        self.run('textbox', path, ['--scrolltext'])

    def calc_height(self, msg):
        height_offset = 8 if msg else 7
        return [str(self.height - height_offset)]

    def menu(self, msg='', items=(), prefix=' - '):
        if isinstance(items[0], string_types):
            items = [(i, '') for i in items]
        else:
            items = [(k, prefix + v) for k, v in items]
        extra = self.calc_height(msg) + flatten(items)
        return self.run('menu', msg, extra).value

    def showlist(self, control, msg, items, prefix):
        if isinstance(items[0], string_types):
            items = [(i, '', 'OFF') for i in items]
        else:
            items = [(k, prefix + v, s) for k, v, s in items]
        extra = self.calc_height(msg) + flatten(items)
        return shlex.split(self.run(control, msg, extra).value)

    def radiolist(self, msg='', items=(), prefix=' - '):
        return self.showlist('radiolist', msg, items, prefix)

    def checklist(self, msg='', items=(), prefix=' - '):
        return self.showlist('checklist', msg, items, prefix)

    def submenu(self, msg='', items=(), name_property='name', subitems_property='subitems'):
        item_names = []
        for i, v in enumerate(items):
            item_name = '[' + str(i) + ']' + v[name_property]
            if subitems_property in v:
                item_name += " >>"
            item_names.append(item_name)

        choice = self.menu(msg, item_names)
        choice = choice.decode('utf-8')
        choice_digit = re.search(r"^\[(\d+)\]", str(choice))
        if not choice_digit:
            print('Not a valid submenu:')
            return

        item = items[int(choice_digit[1])]

        if subitems_property in item:
            return self.submenu(msg, item[subitems_property], name_property, subitems_property)

        return item

################
## I/O classes

class Io:
    """
    Input output class as a wrapper to transfer data from source to destination
    """
    def _validateTarget(self, target=None):
        # First lets see if this is a legit path/file
        if os.path.exists(target):
            return True
        result = urlparse(target)
        if result.scheme in ['http', 'https', 'ftp', 'ftps', 'scp', 'sftp', 'file']:
            return True
        return False

    def __init__(self, target):
        self._target_path = target
        self.target = None
        self.size = -1

    def open(self):
        pass

    def close(self):
        if self.target:
            self.target.close()

    def read(self, bsize=40960):
        return self.target.read(bsize)

    def write(self, data):
        return self.target.write(data)

    def seek(self, pos=None):
        if pos:
            return self.target.seek(pos)


class FileIo(Io):
    """build file IO with hashfile to validate content"""
    def __init__(self, target_path=None, mode=None, withHash=False):
        if not mode and not self._validateTarget(target_path):
            mode = 'wb'
        super().__init__(target_path)
        self._mode = mode
        self.pipe = None
        self._withHash = withHash
        if withHash:
            self.hashFile = HashFile(target_path)

    def open(self):
        self.target = open(self._target_path, self._mode)
        if self._withHash and self._mode == 'wb':
            self.hashFile._open()
        if self.target.name != '/dev/stdout' and self.target.name != '/dev/stdin':
            self.size  = os.stat(self.target.name).st_size
            self.pipe  = False
        else:
            self.size  = None
            self.pipe  = True

    def write(self, data):
        if self._withHash:
            if self.hashFile:
                self.hashFile._update(data)
        return self.target.write(data)

    def close(self):
        if self.target:
            self.target.close()
        if self._withHash:
            if self.hashFile:
                self.hashFile._close()

    def is_existing_file(self):
        if os.path.exists(os.path.dirname(self._target_path)):
            if os.path.exists(self._target_path):
                return os.path.isfile(self._target_path)
        return False

class HttpIo(Io):
    """use http as source for transfer"""
    def __init__(self, target_path=None):
        super().__init__(target_path)
        self.response  = None

    def open(self):
        self._response = requests.get(self._target_path, stream=True)
        self.target = self._response.raw
        self.size = int(self._response.headers.get('content-length'))

    def close(self):
        if self._response:
            self._response.close()


class ZipFileIo(Io):
    """use zip archive as source for transfer"""
    def __init__(self, target_path=None, member_target=None, mode=None):
        if not self._validateTarget(target_path):
            mode = 'x'
        super().__init__(target_path)
        self._mode = mode
        self._member_target = member_target

    def open(self):
        self._zip = zipfile.ZipFile(self._target_path, self._mode)
        try:
            member_info = self._zip.getinfo(self._member_target)
            self.size = member_info.file_size
            self.target = self._zip.open(member_info)
        except:
            self._zip.close()
            raise

    def close(self):
        if self.target:
            self.target.close()
            self.target = None
        if self._zip:
            self._zip.close()
            self._zip = None

class LZMAFileIo(Io):
    """use LZMA archive as source of data"""
    def __init__(self, target_path=None, mode="rb", size=None):
        if not self._validateTarget(target_path):
            mode = 'w'
        super().__init__(target_path)
        self.size = size
        self._mode = mode

    def open(self):
        self.target = lzma.LZMAFile(self._target_path, self._mode)

class GZipFileIo(Io):
    """use gzip archive as source for data"""
    def __init__(self, target_path=None, mode="rb", size=None):
        if not self._validateTarget(target_path):
            mode = 'w'
        super().__init__(target_path)
        self.size = size
        self._mode = mode

    def open(self):
        self.target = gzip.open(self._target_path, self._mode)

def extract_img(src_path, dst_path, total_size):
    """extract file from archive"""
    archive_basename = os.path.basename(src_path)
    archive_ext = os.path.splitext(archive_basename)
    archive_compression = archive_ext[1]
    image_filename = os.path.basename(dst_path)

    if archive_compression == '.zip':
        src = ZipFileIo(src_path, image_filename, "r")
    if archive_compression == '.xz':
        src = LZMAFileIo(src_path, 'rb', total_size)
    if archive_compression == '.gz':
        src = GZipFileIo(src_path, 'rb', total_size)
    dst = FileIo(dst_path, 'wb')
    Transfer(src, dst, prefix='').start()

###################
## HashFile class

class HashFile(object):
    """create a hashfile that calculates and stores the hash with the file"""
    def __init__(self, target_path):
        self._target_path = target_path
        target_path_split = os.path.split(self._target_path)
        self._sha_path = "{0}/.{1}.sha265".format(
            target_path_split[0],
            target_path_split[1]
        )

        self._sha_obj = None

    def updateHash(self):
        if not self._file_exists():
            raise FileNotFoundError(self._target_path)

        BUF_SIZE = 40960

        try:
            self._open()
            with open(self._target_path, 'rb') as f:
                buff = f.read(BUF_SIZE)
                while buff:
                    self._update(buff)
                    buff = f.read(BUF_SIZE)

            self._close()
        except:
            raise

    def getHash(self):
        if not self._sha_file_valid():
            self.updateHash()

        return self._get_sha_data_raw()['sha256']

    def _open(self):
        self._sha_obj = hashlib.sha256()

    def _update(self, block):
        if self._sha_obj:
            self._sha_obj.update(block)

    def _close(self):
        if self._sha_obj:
            mtime = os.path.getmtime(self._target_path)
            shainfo_hash = self._hash_shainfo(
                self._sha_obj.hexdigest(),
                mtime
            )

            shainfo = {
                "sha256": self._sha_obj.hexdigest(),
                "mtime": mtime,
                "_hash" : shainfo_hash
            }
            with open(self._sha_path, 'w') as f:
                json.dump(shainfo, f, indent=2)

    def _sha_file_valid(self):
        if not self._sha_exists():
            return False

        try:
            data = self._get_sha_data_raw()
            shainfo_hash = self._hash_shainfo(
                data['sha256'],
                data['mtime']
            )
            return shainfo_hash == data['_hash']

        except:
            return False

    def _get_sha_data_raw(self):
        with open(self._sha_path, 'rb') as f:
            data = json.load(f)
        return data

    def _hash_shainfo(self, sha256, mtime):
        sha = hashlib.sha256()
        sha.update(json.dumps({"sha256": sha256, "mtime": mtime}, sort_keys=True).encode('utf-8'))
        return "{0}".format(sha.hexdigest())

    def _file_exists(self):
        return self._is_exitsing_file(self._target_path)

    def _sha_exists(self):
        return self._is_exitsing_file(self._sha_path)

    def _is_exitsing_file(self, target_path):
        if os.path.exists(os.path.dirname(target_path)):
            if os.path.exists(target_path):
                return os.path.isfile(target_path)
        return False

###################
## Transfer class

class Transfer(Output):
    """transfer files form source IO to destination IO with progress bar"""
    global BUF_SIZE
    def __init__(
            self,
            src=None,
            dst=None,
            bsize=BUF_SIZE,
            quiet=False,
            prefix=''
    ):
        Output.__init__(self)
        self.src   = src
        self.dst   = dst
        self.bsize = bsize
        self.quiet = quiet
        self.prefix = prefix

    def start(self):
        totsze = 0
        try:
            st     = time.time()
            self.src.open()
            self.dst.open()

            buff   = self.src.read(self.bsize)
            while buff:
                self.dst.write(buff)
                totsze += len(buff)
                if self.src.size != -1:
                    self.display(self.src.size, totsze, totsze, st, self.prefix)
                else:
                    self.display(None, totsze, totsze, st, self.prefix)
                buff = self.src.read(self.bsize)
            time.sleep(0.1)
            self.display(self.src.size, self.src.size, self.src.size, st)
            time.sleep(0.1)
            self.clear_display()

        except KeyboardInterrupt:
            print
            sys.exit(1)
        finally:
            self.src.close()
            self.dst.close()

###################
## helpers

def flatten(data):
    return list(itertools.chain.from_iterable(data))

def get_jsonparsed_data(url):
    response = requests.get(url)
    data = response.content.decode("utf-8")
    return json.loads(data)


def build_oslist(os_list_url):
    os_list = get_jsonparsed_data(os_list_url)["os_list"]
    for os in os_list:
        if 'subitems_url' in os:
            os['subitems'] = build_oslist(os['subitems_url'])
    return os_list

def get_disk_info(disk_name=None):
    cmd = ['lsblk', '-JOb']
    discs_info_json = str(subprocess.check_output(cmd).decode('utf-8'))
    disk_info = json.loads(discs_info_json)['blockdevices']
    if not disk_name:
        return json.loads(discs_info_json)['blockdevices']
    else:
        for disk in disk_info:
            if disk['name'] == disk_name:
                return disk

    raise FileNotFoundError(disk_name)

def disk_has_mounts(disk_name):
    disk_info = get_disk_info(disk_name)
    if disk_info['mountpoint']:
        return True
    if 'children' in disk_info:
        for child in disk_info['children']:
            if child['mountpoint']:
                return True
    return False

def ensure_path_exists(directory):
    if not os.path.exists(directory):
        os.makedirs(directory)

def file_exists(filepath):
    if os.path.exists(os.path.dirname(filepath)):
        if os.path.exists(filepath):
            return os.path.isfile(filepath)

    return False

def ensure_root():
    if not os.getuid() == 0:
        sys.exit(STR_NO_ROOT)

###################
## main


## init
if ENV != 'dev':
    ensure_root()

ensure_path_exists(CACHE_DOWNLOAD_PATH)
ensure_path_exists(CACHE_IMAGE_PATH)

## get choices
os_list = build_oslist(OS_LIST_URL)

WT = Whiptail(
    STR_TITLE,
    STR_BACKTITLE,
    WHIPTAIL_HEIGHT,
    WHIPTAIL_WIDTH
)

try:
    if ENV == 'dev':
        selected_os = os_list[1]['subitems'][0]
    else:
        selected_os = WT.submenu(STR_SELECT_OS, os_list)
except:
    print(STR_ABORT_OS_SELECTION)
    raise

disks_info = get_disk_info()
selectable_disks = []

for disk in disks_info:
    if not disk_has_mounts(disk['name']):
        disk["display_name"] = '{0} ({1})'.format(
            disk['name'],
            HumanReadable().size(disk['size'])
        )
        selectable_disks.append(disk)

if len(selectable_disks) == 0:
    WT.alert(STR_NO_AVAILABLE_STORAGE)
    sys.exit()

try:
    if ENV == 'dev':
        selected_disk = selectable_disks[0]
    else:
        selected_disk = WT.submenu(
            STR_SELECT_DEVICE,
            selectable_disks,
            name_property='display_name'
        )
except:
    print(STR_ABORT_DEVICE_SELECTION)
    raise

if ENV != 'dev':
    if not WT.confirm(STR_CONFIRM_INSTALL.format(
            selected_os['name'],
            selected_disk['name']
        )):
        WT.alert(STR_ABORT_INSTALL)
        sys.exit()

## run imaging

header_str = "{0}\n{1}{2}\n{0}".format(
    STR_HR,
    STR_HEADER_PADDING,
    STR_BACKTITLE
)
summary_str = STR_SUMMARY.format(
    selected_os['name'],
    selected_disk['name']
)

print("{0}\n\n{1}\n\n".format(header_str, summary_str))

download_url = selected_os['url']
download_filename = os.path.basename(download_url)
download_filepath = os.path.join(CACHE_DOWNLOAD_PATH, download_filename)
download_ext = os.path.splitext(download_filename)
download_compression = download_ext[1]
download_basename = download_ext[0]
if download_ext[0].endswith('img'):
    download_basename = os.path.splitext(download_ext[0])[0]
image_filename = download_basename + ".img"
image_filepath = os.path.join(CACHE_IMAGE_PATH, image_filename)

print(" - {0}".format(STR_RETRIEVING.format(STR_IMG)))
print("    - {0}".format(STR_CHECKING_CACHE))

img_source = HttpIo(download_url)
download_file = FileIo(download_filepath, 'wb', withHash=True)
image_file = FileIo(image_filepath, 'rb', withHash=True)
drive_target = FileIo("/dev/{0}".format(selected_disk['name']), 'wb')


image_cached = False
if 'extract_sha256' in selected_os and image_file.is_existing_file():
    os_image_sha = selected_os["extract_sha256"]
    if os_image_sha == image_file.hashFile.getHash():
        image_cached = True

if image_cached:
    print("    ✔ {0}".format(STR_AVAILABLE.format(STR_IMG, STR_CACHE)))
    print(" ✔ {0}".format(STR_AVAILABLE.format(STR_IMG, STR_CACHE)))
else:
    print("    - {0}".format(STR_RETRIEVING.format(STR_IMG_ARCHIVE)))

    download_cached = False
    if 'image_download_sha256' in selected_os and download_file.is_existing_file():
        print("       - {0}".format(STR_CHECKING_CACHE))
        download_image_sha = selected_os["image_download_sha256"]
        if  download_image_sha == download_file.hashFile.getHash():
            download_cached = True
    if download_cached:
        print("    ✔ {0}".format(STR_AVAILABLE.format(STR_IMG_ARCHIVE, STR_CACHE)))
    else:
        print("      {0}".format(STR_DOWNLOADING.format(STR_IMG_ARCHIVE)))
        Transfer(img_source, download_file, prefix='').start()
        print("    ✔ {0}".format(STR_AVAILABLE.format(STR_IMG_ARCHIVE, STR_DOWNLOAD)))

    print("    - {0}".format(STR_EXTRACTING.format(STR_IMG, STR_IMG_ARCHIVE)))

    extract_img(download_filepath, image_filepath, total_size=selected_os["extract_size"])
    print("    ✔ {0}".format(STR_AVAILABLE.format(STR_IMG, STR_IMG_ARCHIVE)))
    print(" ✔ {0}".format(STR_AVAILABLE.format(STR_IMG, STR_IMG_ARCHIVE)))

print(" - {0}".format(STR_WRITING_IMG.format(
    selected_os['name'],
    selected_disk['name']
)))
Transfer(image_file, drive_target, prefix='').start()
os.sync()
print(" ✔ {0}".format(STR_IMG_INSTALLED.format(
    selected_os['name'],
    selected_disk['name']
)))

print(STR_SUCCESS)
