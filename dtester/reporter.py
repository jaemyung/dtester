# reporter.py
#
# Copyright (c) 2006-2010 Markus Wanner
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE).

"""
reporting of progress and test results
"""

import sys, time, traceback
from twisted.internet import defer
from twisted.python import failure
from dtester.test import BaseTest, TestSuite
import exceptions

class Reporter:
    """ An abstract base class for all reporters.
    """

    def __init__(self, outs=sys.stdout, errs=sys.stderr):
        """ @param outs: output stream for progress and result information
            @type  outs: file handle
            @param errs: error stream for reporting errors
            @type  errs: file handle
        """
        self.outs = outs
        self.errs = errs

        self.results = {}
        self.suite_failures = {}

    def getDescription(self, suite, attname=None):
        """ @return: the test's description or that of one of its methods,
                     i.e. the setUpDescription.
        """
        # FIXME: shouldn't this be part of the BaseTest class?
        #
        # We either have a someThingDescription attribute or the main test's
        # description attribute (note the lower case there).
        if attname:
            attname += "Description"
        else:
            attname = "description"
        if not hasattr(suite, attname):
            # raise Exception("Test %s misses attribute %s." % (suite, attname))
            return "no desc"
        attr = getattr(suite, attname)
        if isinstance(attr, str):
            return attr
        else:
            try:
                desc = attr()
            except Exception, e:
                desc = "EXCEPTION in description of %s: %s" % (
                    suite, e)
            return desc

    def dumpError(self, tname, err):
        assert isinstance(err, failure.Failure)
        inner_err = err.value

        # extract FirstError's, as throws from a DeferredList
        while isinstance(inner_err, defer.FirstError):
            err = inner_err.subFailure
            inner_err = err.value

        if isinstance(inner_err, exceptions.TestFailure):
            msg = "=" * 20 + "\n"
            msg += "%s failed: %s\n" % (tname, inner_err.message)
            if inner_err.getDetails():
                msg += "-" * 20 + "\n"
                msg += inner_err.getDetails() + "\n"
            self.errs.write(msg + "\n")
        else:
            msg = "=" * 20 + "\n"
            msg += "Error in test %s:\n" % (tname,)
            msg += "-" * 20 + "\n"
            msg += repr(err) + "\n"
            msg += "-" * 20 + "\n"
            self.errs.write(msg)
            err.printBriefTraceback(self.errs)
            self.errs.write("\n")

    def dumpErrors(self):
        for tname, (result, err) in self.results.iteritems():
            if not result:
                self.dumpError(tname, err)

        for suite_name, err in self.suite_failures.iteritems():
            self.dumpError(suite_name, err)


class StreamReporter(Reporter):
    """ A simple, human readable stream reporter without any bells and
        whistles. Can get confusing to read as it dumps a lot of output.
    """

    def begin(self, tdef):
        self.t_start = time.time()

    def end(self, result, error):
        self.dumpErrors()

        self.t_end = time.time()

        count_succ = 0
        for tname, (result, err) in self.results.iteritems():
            if result:
                count_succ += 1

        if count_succ == len(self.results):
            msg = "%d tests processed successfully in %0.1f seconds.\n" % (
                count_succ, (self.t_end - self.t_start))
        else:
            ratio = float(count_succ) / float(len(self.results)) * 100
            msg = "%d of %d tests succeeded (%0.1f%%), " % (
                    count_succ, len(self.results), ratio) + \
                  "processed in %0.1f seconds.\n" % (
                    (self.t_end - self.t_start,))
        self.outs.write(msg)
        self.outs.flush()

    def startTest(self, tname, test):
        self.outs.write("        %s: test started\n" % (tname,))
        self.outs.flush()

    def stopTest(self, tname, test, result, error):
        desc = self.getDescription(test)
        self.results[tname] = (result, error)
        if result:
            msg = "OK:     %s: %s\n" % (tname, desc)
        else:
            tb = traceback.extract_tb(error.getTracebackObject())
            try:
                row = tb.pop()

                # the last row of the traceback might well one of the standard
                # check methods in the BaseTest class. We don't want to display
                # that.
                while row[2] in ('assertEqual', 'assertNotEqual', 'syncCall'):
                    row = tb.pop()

                filename = row[0]
                lineno = row[1]

                errmsg = error.getErrorMessage()
                msg = "FAILED: %s: %s - %s in %s:%d\n" % (
                    tname, desc, errmsg, filename, lineno)
            except IndexError:
                errmsg = error.getErrorMessage()
                msg = "FAILED: %s %s - %s" % (tname, desc, errmsg)

        self.outs.write(msg)
        self.outs.flush()

    def startSetUpSuite(self, tname, suite):
        desc = self.getDescription(suite, "setUp")
        self.outs.write("        %s: %s\n" % (tname, desc))
        self.outs.flush()

    def stopSetUpSuite(self, tname, suite):
        pass

    def startTearDownSuite(self, tname, suite):
        desc = self.getDescription(suite, "tearDown")
        self.outs.write("        %s: %s\n" % (tname, desc))
        self.outs.flush()

    def stopSetUpSuite(self, tname, suite):
        pass

    def suiteSetUpFailure(self, tname, suite, error):
        tb = error.getTracebackObject()
        msg = error.getErrorMessage()

        self.outs.write("ERROR:  %s: failed setting up: %s\n" % (tname, msg))
        self.outs.flush()
        self.suite_failures[tname] = error

    def suiteTearDownFailure(self, tname, suite, error):
        msg = error.getErrorMessage()
        self.outs.write("ERROR:  %s: failed tearing down\n" % (tname, msg))
        self.outs.flush()
        self.suite_failures[tname] = error


class TapReporter(Reporter):
    """ A (hopefully) TAP compatible stream reporter, useful for automated
        processing of test results.

        @note: compatibility with other TAP tools is mostly untested.
    """

    def begin(self, tdefs):
        self.t_start = time.time()

        # map test names to TAP numbers
        self.numberMapping = {}
        nr = 0
        for (tname, tdef) in tdefs.iteritems():
            if issubclass(tdef['class'], BaseTest) and \
                    not issubclass(tdef['class'], TestSuite):
                nr += 1
                self.numberMapping[tname] = nr
        self.outs.write("TAP version 13\n")
        self.outs.write("1..%d\n" % nr)

    def end(self, result, error):
        self.t_end = time.time()

        count_succ = 0
        for tname, (result, error) in self.results.iteritems():
            if result:
                count_succ += 1

        #for suite_name, err in self.suite_failures.iteritems():
        #    self.errs.write("Suite %s failed:\n" % suite_name)
        #    self.errs.write(str(err) + "\n\n")

        if count_succ == len(self.results):
            msg = "# %d tests processed successfully in %0.1f seconds.\n" % (
                count_succ, (self.t_end - self.t_start))
        else:
            ratio = float(count_succ) / float(len(self.results)) * 100
            msg = "# %d of %d tests succeeded (%0.1f%%), " % (
                    count_succ, len(self.results), ratio) + \
                  "processed in %0.1f seconds.\n" % (
                    (self.t_end - self.t_start,))
        self.outs.write(msg)
        self.outs.flush()

    def startTest(self, tname, test):
        self.outs.write("#        %s: test started\n" % (tname,))
        self.outs.flush()

    def stopTest(self, tname, test, result, error):
        desc = self.getDescription(test)
        self.results[tname] = (result, error)
        if result:
            msg = "ok %d - %s: %s\n" % (
                self.numberMapping[tname], tname, desc)
        else:
            errmsg = error.getErrorMessage()
            tb = traceback.extract_tb(error.getTracebackObject())
            try:
                row = tb.pop()

                # the last row of the traceback might well one of the standard
                # check methods in the BaseTest class. We don't want to display
                # that.
                while row[2] in ('assertEqual', 'assertNotEqual', 'syncCall'):
                    row = tb.pop()

                filename = row[0]
                lineno = row[1]

                msg = "not ok %d - %s: %s # %s in %s:%d\n" % (
                    self.numberMapping[tname], tname, desc,
                    errmsg, filename, lineno)
            except IndexError:
                msg = "not ok %d - %s: %s # %s\n" % (
                    self.numberMapping[tname], tname, desc, errmsg)

        self.outs.write(msg)
        self.outs.flush()

    def startSetUpSuite(self, tname, suite):
        desc = self.getDescription(suite, "setUp")
        self.outs.write("# %s: %s\n" % (tname, desc))
        self.outs.flush()

    def stopSetUpSuite(self, tname, suite):
        pass

    def startTearDownSuite(self, tname, suite):
        desc = self.getDescription(suite, "tearDown")
        self.outs.write("# %s: %s\n" % (tname, desc))
        self.outs.flush()

    def stopTearDownSuite(self, tname, suite):
        pass

    def suiteSetUpFailure(self, tname, suite, error):
        tb = error.getTracebackObject()
        msg = error.getErrorMessage()

        self.outs.write("# ERROR: %s: failed setting up: %s\n" % (tname, msg))
        self.outs.flush()
        self.suite_failures[tname] = error

    def suiteTearDownFailure(self, tname, suite, error):
        msg = error.getErrorMessage()
        self.outs.write("# ERROR: %s: failed tearing down\n" % (tname, msg))
        self.outs.flush()
        self.suite_failures[tname] = error


class CursesReporter(Reporter):
    """ A more advanced reporter for terminal users based on curses
        functionality. Concentrates on test results and emits setUp and
        tearDown information only as vanishing status lines.
    """

    def __init__(self, outs=sys.stdout, errs=sys.stderr):
        Reporter.__init__(self, outs, errs)
        self.count_result_lines = 0
        self.count_status_lines = 0

        # initialize curses
        import curses
        curses.setupterm()

        # required terminal capabilities
        self.CURSOR_UP = curses.tigetstr('cuu1')
        self.CURSOR_BOL = curses.tigetstr('cr')
        self.CURSOR_DOWN = curses.tigetstr('cud1')
        self.CLEAR_EOL = curses.tigetstr('el')
        self.NORMAL = curses.tigetstr('sgr0')
        self.COLUMNS = curses.tigetnum('cols')

        setf = curses.tigetstr('setf')
        setaf = curses.tigetstr('setaf')
        if setf:
            self.COLOR_BLUE = curses.tparm(setf, 1)
            self.COLOR_GREEN = curses.tparm(setf, 2)
            self.COLOR_RED = curses.tparm(setf, 4)
        elif setaf:
            self.COLOR_BLUE = curses.tparm(setaf, 4)
            self.COLOR_GREEN = curses.tparm(setaf, 2)
            self.COLOR_RED = curses.tparm(setaf, 1)
        else:
            self.COLOR_BLUE = ""
            self.COLOR_GREEN = ""
            self.COLOR_RED = ""

        # the lines themselves, by test name
        self.lines = {}

        # test name to line position mapping for results and status
        self.resultLines = []
        self.statusLines = []

    def addResultLine(self, tname, str):
        self.lines[tname] = str
        self.resultLines.append(tname)
        self.count_result_lines += 1

        out = ""
        out += self.CURSOR_UP * self.count_status_lines
        out += str + self.CLEAR_EOL + self.CURSOR_DOWN

        # rewrite all status lines
        out += self.getStatusLines()
        self.outs.write(out)
        self.outs.flush()

    def updateResultLine(self, tname, str):
        self.lines[tname] = str

        out = ""
        idx = self.resultLines.index(tname)
        offset = self.count_status_lines + self.count_result_lines - idx
        out += self.CURSOR_UP * offset + self.CURSOR_BOL
        out += str + self.CLEAR_EOL
        out += self.CURSOR_DOWN * offset
        self.outs.write(out)
 
    def addStatusLine(self, tname, str):
        self.lines[tname] = str
        self.statusLines.append(tname)
        self.count_status_lines += 1

        out = str + self.CLEAR_EOL + self.CURSOR_DOWN
        self.outs.write(out)
        self.outs.flush()

    def dropStatusLine(self, tname):
        out = ""

        idx = self.statusLines.index(tname)
        offset = self.count_status_lines - idx
        out += self.CURSOR_UP * offset + self.CURSOR_BOL + self.CLEAR_EOL

        # remove the line from internal tracking structures
        del self.lines[tname]
        self.statusLines.remove(tname)
        self.count_status_lines -= 1

        if idx < len(self.statusLines):
            out += self.getStatusLines(idx)

        # clear the last line, which should now be empty
        out += self.CLEAR_EOL

        self.outs.write(out)
        self.outs.flush()

    def getStatusLines(self, offset=0):
        out = ""
        for tname in self.statusLines[offset:]:
            out += self.lines[tname] + self.CLEAR_EOL + self.CURSOR_DOWN
        return out

    def begin(self, tdefs):
        self.t_start = time.time()

    def end(self, result, error):
        self.dumpErrors()

        self.t_end = time.time()

        count_succ = 0
        for tname, (result, error) in self.results.iteritems():
            if result:
                count_succ += 1

        if count_succ == len(self.results):
            msg = "%d tests processed successfully in %0.1f seconds.\n" % (
                count_succ, (self.t_end - self.t_start))
        else:
            ratio = float(count_succ) / float(len(self.results)) * 100
            msg = "%d of %d tests succeeded (%0.1f%%), " % (
                    count_succ, len(self.results), ratio) + \
                  "processed in %0.1f seconds.\n" % (
                    (self.t_end - self.t_start,))

        self.outs.write(msg)
        self.outs.flush()

    def startTest(self, tname, test):
        desc = self.getDescription(test)
        msg = self.renderResultLine("running", tname, desc)
        self.addResultLine(tname, msg)

    def renderResultLine(self, result, tname, tdesc, errmsg=None,
                         filename=None, lineno=None):
        columns = self.COLUMNS
        rest = columns

        # first 7 chars for the result
        if result == "running":
            msg = "running"
        elif result == "OK":
            msg = self.COLOR_GREEN + "     OK" + self.NORMAL
        elif result == "FAILED":
            msg = self.COLOR_RED + " FAILED" + self.NORMAL
        elif result == "SKIPPED":
            msg = self.COLOR_BLUE + "SKIPPED" + self.NORMAL
        else:
            raise Exception("unknown result: '%s'" % result)

        # add the test name
        msg += " " + tname + ": "
        rest = columns - 3 - 7 - len(tname)

        right = ""
        if filename and lineno:
            if len(filename) > 20:
                filename = ".." + filename[-17:]
            add = " %s:%d" % (filename, lineno)
            rest -= len(add)
            right = add

        if errmsg and rest > 5:
            errmsg = errmsg.replace("\n", " ")
            if len(errmsg) > rest:
                errmsg = " " + errmsg[:rest-4] + ".."
                rest = 0
            else:
                rest -= len(errmsg) + 1
            right = errmsg + " " + right

        if rest > 5:
            if len(tdesc) > rest:
                tdesc = tdesc[:rest-3] + ".."
                rest = 0
            else:
                rest -= len(tdesc) + 1
            msg += tdesc

        return msg + " " * rest + right

    def stopTest(self, tname, test, result, error):
        desc = self.getDescription(test)
        self.results[tname] = (result, error)

        if result:
            msg = self.renderResultLine("OK", tname, desc)
        else:
            tb = traceback.extract_tb(error.getTracebackObject())
            try:
                row = tb.pop()

                # the last row of the traceback might well one of the standard
                # check methods in the BaseTest class. We don't want to display
                # that.
                while row[2] in ('assertEqual', 'assertNotEqual', 'syncCall'):
                    row = tb.pop()

                filename = row[0]
                lineno = row[1]

                errmsg = error.getErrorMessage()
            except IndexError:
                filename = None
                lineno = None
                errmsg = error.getErrorMessage()

            msg = self.renderResultLine("FAILED", tname, desc,
                                        errmsg, filename, lineno)

        self.updateResultLine(tname, msg)

    def startSetUpSuite(self, tname, suite):
        desc = self.getDescription(suite, "setUp")
        msg = "%s: %s" % (tname, desc)
        self.addStatusLine("setup__" + tname, msg)
        self.outs.flush()

    def stopSetUpSuite(self, tname, suite):
        self.dropStatusLine("setup__" + tname)

    def startTearDownSuite(self, tname, suite):
        desc = self.getDescription(suite, "tearDown")
        # self.dropStatusLine(tname)
        msg = "%s: %s" % (tname, desc)
        self.addStatusLine("teardown__" + tname, msg)
        self.outs.flush()

    def stopTearDownSuite(self, tname, suite):
        self.dropStatusLine("teardown__" + tname)

    def suiteSetUpFailure(self, tname, suite, error):
        tb = error.getTracebackObject()
        msg = error.getErrorMessage()

        #self.outs.write("# ERROR: %s: failed setting up: %s\n" % (tname, msg))
        self.outs.flush()
        self.suite_failures[tname] = error

    def suiteTearDownFailure(self, tname, suite, error):
        msg = error.getErrorMessage()
        #self.outs.write("# ERROR: %s: failed tearing down\n" % (tname, msg))
        self.outs.flush()
        self.suite_failures[tname] = error

def reporterFactory():
    if sys.stdout.isatty():
        return CursesReporter()
    else:
        return StreamReporter()

