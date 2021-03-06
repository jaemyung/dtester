# reporter.py
#
# Copyright (c) 2006-2015 Markus Wanner
#
# Distributed under the Boost Software License, Version 1.0. (See
# accompanying file LICENSE).

"""
reporting of progress and test results
"""

import os, sys, traceback
from twisted.internet import defer
from twisted.python import failure
from dtester.test import BaseTest, TestSuite
from dtester.exceptions import TestFailure, TimeoutError, TestSkipped, \
    DefinitionError, FailureCollection, UnableToRun, FailedDependencies


class Reporter:
    """ An abstract base class for all reporters.
    """

    def __init__(self, outs=sys.stdout, errs=sys.stderr,
                 showTimingInfo=True, showLineNumbers=True):
        """ @param outs: output stream for progress and result information
            @type  outs: file handle
            @param errs: error stream for reporting errors
            @type  errs: file handle
        """
        self.outs = outs
        self.errs = errs
        self.showTimingInfo = showTimingInfo
        self.showLineNumbers = showLineNumbers

    def getDescription(self, suite, attname=None):
        """ @return: the test's description or that of one of its methods,
                     i.e. the setUpDescription.
        """
        # FIXME: shouldn't this be part of the BaseTest class?
        #
        # We either have a someThingDescription attribute or the main test's
        # description attribute (note the lower case there).
        if not suite:
            return None
        if attname:
            fullAttname = attname + "Description"
        else:
            fullAttname = "description"
        if not hasattr(suite, fullAttname):
            if attname:
                return "(no description for %s of %s)" % (attname, repr(suite))
            else:
                # Test itself has no further description
                return None
        attr = getattr(suite, fullAttname)
        if attr is None:
            # intentionally no description given
            return ""
        elif isinstance(attr, str):
            return attr
        else:
            try:
                desc = attr()
            except Exception, e:
                desc = "EXCEPTION in description of %s: %s" % (suite, e)
            return desc

    def getInnerError(self, error):
        tb = None
        tbo = None
        while True:
            if isinstance(error, failure.Failure):
                tb = error.getTraceback()
                tbo = error.getTracebackObject()
                error = error.value
            elif isinstance(error, defer.FirstError):
                error = error.subFailure
                assert isinstance(error, failure.Failure)
            else:
                return (error, tb, tbo)

    def getShortError(self, error):
        (inner_error, tb, tbo) = self.getInnerError(error)
        tbo = traceback.extract_tb(error.getTracebackObject())

        try:
            row = tbo.pop()

            # the last row of the traceback might well be one of the standard
            # check methods in the BaseTest class. We don't want to display
            # that.
            while row[2] in ('assertEqual', 'assertNotEqual', 'syncCall'):
                row = tbo.pop()

            commonpath = os.path.commonprefix((row[0], os.getcwd()))
            filename = row[0][len(commonpath) + 1:]
            lineno = row[1]

        except IndexError:
            filename = None
            lineno = None

        errmsg = repr(inner_error)

        # skip filename and line number for DefinitionErrors and
        # FailedDependencies
        if isinstance(inner_error, DefinitionError) or \
            isinstance(inner_error, FailedDependencies):
            filename = None
            lineno = None

        return (errmsg, filename, lineno)

    def dumpError(self, tname, type, err):
        assert isinstance(err, failure.Failure)

        (inner_err, tb, ignored) = self.getInnerError(err)

        if isinstance(inner_err, FailureCollection):
            msg = "=" * 20 + "\n"
            msg += "%s %s failed: collected %d errors:\n" % (
                type, tname, len(inner_err.getErrors()))
            msg += ("-" * 20 + "\n")
            details = []
            for err in inner_err.getErrors():
                if isinstance(err, TestFailure):
                    desc = repr(err)
                    detail = err.getDetails()
                    if detail is None:
                        details.append(desc)
                    else:
                        details.append("Error: %s\nDetails:\n%s" % (
                            desc, detail))
                elif isinstance(err, TimeoutError):
                    details.append("timeout error")
                else:
                    details.append(repr(err))
            msg += ("\n" + "-" * 20 + "\n").join(details)
            msg += "\n"
            self.errs.write(msg)
        elif isinstance(inner_err, TestFailure):
            msg = "=" * 20 + "\n"
            msg += "%s %s failed: %s\n" % (type, tname, repr(inner_err))
            if inner_err.getDetails():
                msg += "-" * 20 + "\n"
                msg += inner_err.getDetails() + "\n"
            msg += "\n"
            self.errs.write(msg)
        elif isinstance(inner_err, TimeoutError):
            msg = "=" * 20 + "\n"
            msg += "%s %s: %s\n" % (type, tname, repr(inner_err))
            msg += "-" * 20 + "\n"
            msg += tb + "\n"
            self.errs.write(msg)
        elif isinstance(inner_err, TestSkipped):
            return
        elif isinstance(inner_err, UnableToRun):
            msg = "=" * 20 + "\n"
            msg += "%s %s: unable to run: %s" % (
                type, tname, inner_err.message)
        else:
            msg = "=" * 20 + "\n"
            msg += "Error in %s %s:\n" % (type, tname)
            msg += "-" * 20 + "\n"
            msg += repr(inner_err) + "\n"
            msg += "-" * 20 + "\n"
            msg += tb + "\n"
            self.errs.write(msg)

    def dumpErrors(self, errors):
        if len(errors) > 0:
            self.errs.write("\n")
        for (name, type, error) in errors:
            self.dumpError(name, type, error)

    def harnessFailure(self):
        self.errs.write("Failed running the test harness:\n")
        error.printBriefTraceback(self.errs)

    def dumpResults(self, t_diff, count_total, count_succ, count_skipped,
                    count_xfail, prefix=""):
        if count_succ == count_total:
            msg = "%s%d tests successfully processed" % (
                prefix, count_succ)

            if self.showTimingInfo:
                msg += " in %0.1f seconds" % t_diff

            msg += ".\n"
        else:
            count_failed = (count_total - count_succ - count_skipped -
                            count_xfail)
            run_total = count_total - count_skipped

            msg = "%sRun %s tests" % (prefix, run_total)
            if self.showTimingInfo:
                msg += " in %0.1f seconds" % t_diff

            if count_skipped > 0:
                msg += ", skipped %d" % (count_skipped,)

            msg += ":"

            if count_succ > 0:
                msg += " %d succeeded" % (count_succ,)
            if count_failed > 0:
                msg += " %d failed" % count_failed
            if count_skipped > 0:
                msg += " %d skipped" % count_skipped
            if count_xfail > 0:
                if count_xfail > 1:
                    msg += " %d expected failures" % count_xfail
                else:
                    msg += " 1 expected failure"
            msg += ".\n"

        self.outs.write(msg)
        self.outs.flush()

class StreamReporter(Reporter):
    """ A simple, human readable stream reporter without any bells and
        whistles. Can get confusing to read as it dumps a lot of output.
    """

    def begin(self, tdef):
        pass

    def end(self, t_diff, count_total, count_succ, count_skipped,
            count_xfail, errors):
        self.dumpErrors(errors)
        self.dumpResults(t_diff, count_total, count_succ, count_skipped,
                         count_xfail)

    def startTest(self, tname, test):
        self.outs.write("        %s: test started\n" % (tname,))
        self.outs.flush()

    def stopTest(self, tname, test, result, error):
        desc = self.getDescription(test)
        if not desc and result == "OK":
            return

        msg = str(tname)
        if result in ("OK", "SKIPPED", "UX-OK"):
            if desc:
                msg += ": %s" % desc
            msg += "\n"
        else:
            (errmsg, filename, lineno) = self.getShortError(error)

            if filename and lineno and result != "UX-SKIP":
                if self.showLineNumbers:
                    msg += " - %s in %s:%d\n" % (errmsg, filename, lineno)
                else:
                    msg += " - %s in %s\n" % (errmsg, filename)
            else:
                msg += " - %s\n" % (errmsg,)

        self.writeLine(result, msg)

    def log(self, msg):
        for line in msg.split("\n"):
            # lame attempt at escaping other special characters
            line = repr(line)
            line = line[1:-1]
            self.writeLine("LOG", line + "\n")

    def writeLine(self, mtype, msg):
        msg = mtype + " " * (8 - len(mtype)) + msg
        self.outs.write(msg)
        self.outs.flush()

    def startSetUpSuite(self, tname, suite):
        desc = self.getDescription(suite, "setUp")
        if not desc:
            return
        self.outs.write("        %s: %s\n" % (tname, desc))
        self.outs.flush()

    def stopSetUpSuite(self, tname, suite):
        pass

    def startTearDownSuite(self, tname, suite):
        desc = self.getDescription(suite, "tearDown")
        if not desc:
            return
        self.outs.write("        %s: %s\n" % (tname, desc))
        self.outs.flush()

    def stopTearDownSuite(self, tname, suite):
        pass

    def suiteSetUpFailure(self, tname, error):
        self.outs.write("        suite %s failed setting up\n" % (tname,))
        self.outs.flush()

    def suiteTearDownFailure(self, tname, error):
        msg = error.getErrorMessage()
        self.outs.write("        suite %s: failed tearing down\n" % (tname,))
        self.outs.flush()


class TapReporter(Reporter):
    """ A (hopefully) TAP compatible stream reporter, useful for automated
        processing of test results.

        @note: compatibility with other TAP tools is untested.
    """

    def begin(self, tdefs):
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

    def end(self, t_diff, count_total, count_succ, count_skipped,
            count_xfail, errors):
        self.dumpResults(t_diff, count_total, count_succ, count_skipped,
                         count_xfail, prefix="# ")

    def startTest(self, tname, test):
        self.outs.write("#          %s: test started\n" % (tname,))
        self.outs.flush()

    def stopTest(self, tname, test, result, error):
        desc = self.getDescription(test)
        if not desc and result == "OK":
            return

        if result == "OK":
            msg = "ok %d     - %s: %s\n" % (
                self.numberMapping[tname], tname, desc)
        elif result  == "UX-OK":
            msg = "ok %d - %s (UNEXPECTED)\n" % (
                self.numberMapping[tname], tname)
        else:
            (errmsg, filename, lineno) = self.getShortError(error)

            if result == "UX-SKIP":
                comment = errmsg
            else:
                if filename and lineno:
                    if self.showLineNumbers:
                        comment = "%s in %s:%d" % (errmsg, filename, lineno)
                    else:
                        comment = "%s in %s" % (errmsg, filename)
                else:
                    comment = errmsg

            msg = "not ok %d - %s (%s) # %s\n" % (
                self.numberMapping[tname], tname, result, comment)

        self.outs.write(msg)
        self.outs.flush()

    def startSetUpSuite(self, tname, suite):
        desc = self.getDescription(suite, "setUp")
        if not desc:
            return
        self.outs.write("# %s: %s\n" % (tname, desc))
        self.outs.flush()

    def stopSetUpSuite(self, tname, suite):
        pass

    def startTearDownSuite(self, tname, suite):
        desc = self.getDescription(suite, "tearDown")
        if not desc:
            return
        self.outs.write("# %s: %s\n" % (tname, desc))
        self.outs.flush()

    def stopTearDownSuite(self, tname, suite):
        pass

    def suiteSetUpFailure(self, tname, error):
        tb = error.getTracebackObject()
        msg = error.getErrorMessage()

        self.outs.write("# suite %s: failed setting up\n" % (tname,))
        self.outs.flush()

    def suiteTearDownFailure(self, tname, error):
        msg = error.getErrorMessage()
        self.outs.write("# suite %s: failed tearing down\n" % (tname,))
        self.outs.flush()

    def log(self, msg):
        for line in msg.split("\n"):
            # lame attempt at escaping other special characters
            line = repr(line)
            line = line[1:-1]
            self.outs.write("# log: " + line + "\n")
        self.outs.flush()


class CursesReporter(Reporter):
    """ A more advanced reporter for terminal users based on curses
        functionality. Concentrates on test results and emits setUp and
        tearDown information only as vanishing status lines.
    """

    def __init__(self, outs=sys.stdout, errs=sys.stderr, *args, **kwargs):
        Reporter.__init__(self, outs, errs, *args, **kwargs)
        self.count_result_lines = 0
        self.count_status_lines = 0
        self.count_log_lines = 0

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
            # self.COLOR_BLUE = curses.tparm(setf, 1)
            self.COLOR_GREEN = curses.tparm(setf, 2)
            self.COLOR_CYAN = curses.tparm(setf, 3)
            self.COLOR_RED = curses.tparm(setf, 4)
            self.COLOR_MANGENTA = curses.tparm(setf, 5)
            self.COLOR_YELLOW = curses.tparm(setf, 6)
        elif setaf:
            self.COLOR_RED = curses.tparm(setaf, 1)
            self.COLOR_GREEN = curses.tparm(setaf, 2)
            self.COLOR_YELLOW = curses.tparm(setaf, 3)
            # self.COLOR_BLUE = curses.tparm(setaf, 4)
            self.COLOR_MANGENTA = curses.tparm(setaf, 5)
            self.COLOR_CYAN = curses.tparm(setaf, 6)
        else:
            # self.COLOR_BLUE = ""
            self.COLOR_GREEN = ""
            self.COLOR_CYAN = ""
            self.COLOR_RED = ""
            self.COLOR_YELLOW = ""

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

        if not tname in self.resultLines:
            self.addResultLine(tname, str)
            return

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

    def hasStatusLine(self, tname):
        return tname in self.lines

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
        pass

    def end(self, t_diff, count_total, count_succ, count_skipped,
            count_xfail, errors):
        self.dumpErrors(errors)
        self.dumpResults(t_diff, count_total, count_succ, count_skipped,
                         count_xfail)

    def startTest(self, tname, test):
        desc = self.getDescription(test)
        if not desc:
            return
        msg = self.renderResultLine("running", tname, desc)
        self.addResultLine(tname, msg)

    def log(self, msg):
        columns = self.COLUMNS
        rest = columns

        # first 7 chars for the result
        color = self.COLOR_MANGENTA

        prefix = " " * (8 - len("LOG")) + color + "LOG" + self.NORMAL + " "
        rest = columns - 8 - 1

        for line in msg.split("\n"):
            RIGHT_SPACING = 3
            # lame attempt at escaping other special characters
            line = repr(line)
            line = line[1:-1]
            while len(line) > 0:
                current, line = line[:rest - RIGHT_SPACING], \
                  line[rest - RIGHT_SPACING:]

                self.addResultLine("log" + str(self.count_log_lines),
                                   prefix + current)
                self.count_log_lines += 1

    def renderResultLine(self, result, tname, tdesc, errmsg=None,
                         filename=None, lineno=None):
        columns = self.COLUMNS
        rest = columns

        # first 7 chars for the result
        color = ""
        if result == "OK":
            color = self.COLOR_GREEN
        elif result in ("FAILED", "TIMEOUT", "UX-SKIP"):
            color = self.COLOR_RED
        elif result in ("SKIPPED", "XFAIL"):
            color = self.COLOR_CYAN
        elif result == "UX-OK":
            color = self.COLOR_YELLOW

        msg = " " * (8 - len(result)) + color + result + self.NORMAL

        # add the test name
        msg += " " + tname + ": "
        rest = columns - 3 - 8 - len(tname)

        right = ""
        if filename:
            if len(filename) > 20:
                filename = ".." + filename[-17:]
            if self.showLineNumbers and lineno:
                add = " %s:%d" % (filename, lineno)
            else:
                add = " %s" % (filename,)
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

        if tdesc and rest > 5:
            if len(tdesc) > rest:
                tdesc = tdesc[:rest-3] + ".."
                rest = 0
            else:
                rest -= len(tdesc) + 1
            msg += tdesc

        return msg + " " * rest + right

    def stopTest(self, tname, test, result, error):
        desc = self.getDescription(test)
        if not desc and result == "OK":
            return

        if result in ("OK", "SKIPPED", "UX-OK"):
            msg = self.renderResultLine(result, tname, desc)
        else:
            (errmsg, filename, lineno) = self.getShortError(error)
            msg = self.renderResultLine(result, tname, desc,
                                        errmsg, filename, lineno)

        self.updateResultLine(tname, msg)

    def startSetUpSuite(self, tname, suite):
        desc = self.getDescription(suite, "setUp")
        if not desc:
            return
        msg = "%s: %s" % (tname, desc)
        self.addStatusLine("setup__" + tname, msg)
        self.outs.flush()

    def stopSetUpSuite(self, tname, suite):
        if self.hasStatusLine("setup__" + tname):
            self.dropStatusLine("setup__" + tname)

    def startTearDownSuite(self, tname, suite):
        desc = self.getDescription(suite, "tearDown")
        if not desc:
            return
        # self.dropStatusLine(tname)
        msg = "%s: %s" % (tname, desc)
        self.addStatusLine("teardown__" + tname, msg)
        self.outs.flush()

    def stopTearDownSuite(self, tname, suite):
        if self.hasStatusLine("teardown__" + tname):
            self.dropStatusLine("teardown__" + tname)

    def suiteSetUpFailure(self, tname, error):
        pass

    def suiteTearDownFailure(self, tname, error):
        pass

def reporterFactory():
    if sys.stdout.isatty():
        return CursesReporter()
    else:
        return StreamReporter()

