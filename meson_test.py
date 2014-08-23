#!/usr/bin/env python3

# Copyright 2013-2014 Jussi Pakkanen

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import sys, os, subprocess, time, datetime, pickle, multiprocessing, json
import concurrent.futures as conc
from optparse import OptionParser
import platform

tests_failed = False

parser = OptionParser()
parser.add_option('--wrapper', default=None, dest='wrapper',
                  help='wrapper to run tests with (e.g. valgrind)')
parser.add_option('--wd', default=None, dest='wd',
                  help='directory to cd into before running')
class TestRun():
    def __init__(self, res, returncode, duration, stdo, stde, cmd):
        self.res = res
        self.returncode = returncode
        self.duration = duration
        self.stdo = stdo
        self.stde = stde
        self.cmd = cmd

def write_log(logfile, test_name, result_str, result):
    logfile.write(result_str + '\n\n')
    logfile.write('--- command ---\n')
    logfile.write(' '.join(result.cmd))
    logfile.write('\n--- "%s" stdout ---\n' % test_name)
    logfile.write(result.stdo)
    logfile.write('\n--- "%s" stderr ---\n' % test_name)
    logfile.write(result.stde)
    logfile.write('\n-------\n\n')

def write_json_log(jsonlogfile, test_name, result):
    result = {'name' : test_name,
              'stdout' : result.stdo,
              'stderr' : result.stde,
              'result' : result.res,
              'duration' : result.duration,
              'returncode' : result.returncode,
              'command' : result.cmd}
    jsonlogfile.write(json.dumps(result) + '\n')

def run_with_mono(fname):
    if fname.endswith('.exe') and not platform.system().lower() == 'windows':
        return True
    return False

def run_single_test(wrap, test):
    global tests_failed
    if test.fname.endswith('.jar'):
        cmd = ['java', '-jar', test.fname]
    elif run_with_mono(test.fname):
        cmd = ['mono', test.fname]
    else:
        if test.is_cross:
            if test.exe_runner is None:
                # Can not run test on cross compiled executable
                # because there is no execute wrapper.
                cmd = None
            else:
                cmd = [test.exe_runner, test.fname]
        else:
            cmd = [test.fname]
    if len(wrap) > 0 and 'valgrind' in wrap[0]:
        wrap += test.valgrind_args
    if cmd is None:
        res = 'SKIP'
        duration = 0.0
        stdo = 'Not run because can not execute cross compiled binaries.'
        stde = ''
        returncode = -1
    else:
        cmd = wrap + cmd + test.cmd_args
        starttime = time.time()
        child_env = os.environ.copy()
        child_env.update(test.env)
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             env=child_env)
        (stdo, stde) = p.communicate()
        endtime = time.time()
        duration = endtime - starttime
        stdo = stdo.decode()
        stde = stde.decode()
        if p.returncode == 0:
            res = 'OK'
        else:
            res = 'FAIL'
            tests_failed = True
        returncode = p.returncode
    return TestRun(res, returncode, duration, stdo, stde, cmd)

def print_stats(numlen, tests, name, result, i, logfile, jsonlogfile):
    startpad = ' '*(numlen - len('%d' % (i+1)))
    num = '%s%d/%d' % (startpad, i+1, len(tests))
    padding1 = ' '*(40-len(name))
    padding2 = ' '*(5-len(result.res))
    result_str = '%s %s%s%s%s(%5.2f s)' % \
        (num, name, padding1, result.res, padding2, result.duration)
    print(result_str)
    write_log(logfile, name, result_str, result)
    write_json_log(jsonlogfile, name, result)

def drain_futures(futures):
    for i in futures:
        (result, numlen, tests, name, i, logfile, jsonlogfile) = i
        print_stats(numlen, tests, name, result.result(), i, logfile, jsonlogfile)

def run_tests(options, datafilename):
    logfile_base = 'meson-logs/testlog'
    if options.wrapper is None:
        wrap = []
        logfilename = logfile_base + '.txt'
        jsonlogfilename = logfile_base+ '.json'
    else:
        wrap = [options.wrapper]
        logfilename = logfile_base + '-' + options.wrapper.replace(' ', '_') + '.txt'
        jsonlogfilename = logfile_base + '-' + options.wrapper.replace(' ', '_') + '.json'
    logfile = open(logfilename, 'w')
    jsonlogfile = open(jsonlogfilename, 'w')
    logfile.write('Log of Meson test suite run on %s.\n\n' % datetime.datetime.now().isoformat())
    tests = pickle.load(open(datafilename, 'rb'))
    numlen = len('%d' % len(tests))
    varname = 'MESON_TESTTHREADS'
    if varname in os.environ:
        try:
            num_workers = int(os.environ[varname])
        except ValueError:
            write_log('Invalid value in %s, using 1 thread.' % varname)
            num_workers = 1
    else:
        num_workers = multiprocessing.cpu_count()
    executor = conc.ThreadPoolExecutor(max_workers=num_workers)
    futures = []
    for i, test in enumerate(tests):
        if not test.is_parallel:
            drain_futures(futures)
            futures = []
            res = run_single_test(wrap, test)
            print_stats(numlen, tests, test.name, res, i, logfile, jsonlogfile)
        else:
            f = executor.submit(run_single_test, wrap, test)
            futures.append((f, numlen, tests, test.name, i, logfile, jsonlogfile))
    drain_futures(futures)
    print('\nFull log written to %s.' % logfilename)

if __name__ == '__main__':
    (options, args) = parser.parse_args(sys.argv)
    if len(args) != 2:
        print('Test runner for Meson. Do not run on your own, mmm\'kay?')
        print('%s [data file]' % sys.argv[0])
    if options.wd is not None:
        os.chdir(options.wd)
    datafile = args[1]
    run_tests(options, datafile)
    if tests_failed:
        sys.exit(1)

