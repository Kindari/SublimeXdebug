import sublime
import sublime_plugin
import os
import socket
import base64
import threading
import types
import json
import webbrowser
from xml.dom.minidom import parseString


xdebug_current = None
original_layout = None
debug_view = None
protocol = None
buffers = {}
breakpoint_icon = '../Xdebug/icons/breakpoint'
current_icon = '../Xdebug/icons/current'
current_breakpoint_icon = '../Xdebug/icons/current_breakpoint'


class DebuggerException(Exception):
    pass


class ProtocolException(DebuggerException):
    pass


class ProtocolConnectionException(ProtocolException):
    pass


class Protocol(object):
    '''
    Represents DBGp Protocol Language
    '''

    read_rate = 1024
    port = 9000

    def __init__(self):
        self.port = get_project_setting('port') or get_setting('port') or self.port
        self.clear()

    def clear(self):
        self.buffer = ''
        self.connected = False
        self.listening = False
        self.server = None
        del self.transaction_id
        try:
            self.sock.close()
        except:
            pass
        self.sock = None

    def transaction_id():
        '''
        The transaction_id property.
        '''

        def fget(self):
            self._transaction_id += 1
            return self._transaction_id

        def fset(self, value):
            self._transaction_id = value

        def fdel(self):
            self._transaction_id = 0
        return locals()

    transaction_id = property(**transaction_id())

    def read_until_null(self):
        if self.connected:
            while not '\x00' in self.buffer:
                self.buffer += self.sock.recv(self.read_rate)
            data, self.buffer = self.buffer.split('\x00', 1)
            return data
        else:
            raise(ProtocolConnectionException, "Not Connected")

    def read_data(self):
        length = self.read_until_null()
        message = self.read_until_null()
        if int(length) == len(message):
            return message
        else:
            raise(ProtocolException, "Length mismatch")

    def read(self):
        data = self.read_data()
        #print '<---', data
        document = parseString(data)
        return document

    def send(self, command, *args, **kwargs):
        if 'data' in kwargs:
            data = kwargs['data']
            del kwargs['data']
        else:
            data = None

        tid = self.transaction_id
        parts = [command, '-i %i' % tid]

        if args:
            parts.extend(args)
        if kwargs:
            parts.extend(['-%s %s' % pair for pair in kwargs.items()])
        parts = [part.strip() for part in parts if part.strip()]
        command = ' '.join(parts)
        if data:
            command += ' -- ' + base64.b64encode(data)

        try:
            self.sock.send(command + '\x00')
            #print '--->', command
        except Exception, x:
            raise(ProtocolConnectionException, x)

    def accept(self):
        serv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        if serv:
            try:
                serv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                serv.settimeout(1)
                serv.bind(('', self.port))
                serv.listen(1)
                self.listening = True
                self.sock = None
            except Exception, x:
                raise(ProtocolConnectionException, x)

            while self.listening:
                try:
                    self.sock, address = serv.accept()
                    self.listening = False
                except socket.timeout:
                    pass

            if self.sock:
                self.connected = True
                self.sock.settimeout(None)
            else:
                self.connected = False
                self.listening = False

            try:
                serv.close()
                serv = None
            except:
                pass
            return self.sock
        else:
            raise ProtocolConnectionException('Could not create socket')


class XdebugView(object):
    '''
    The XdebugView is sort of a normal view with some convenience methods.

    See lookup_view.
    '''
    def __init__(self, view):
        self.view = view
        self.current_line = None
        self.context_data = {}
        self.breaks = {}  # line : meta { id: bleh }

    def __getattr__(self, attr):
        if hasattr(self.view, attr):
            return getattr(self.view, attr)
        if attr.startswith('on_'):
            return self
        raise(AttributeError, "%s does not exist" % attr)

    def __call__(self, *args, **kwargs):
        pass

    def center(self, lineno):
        line = self.lines(lineno)[0]
        self.view.show_at_center(line)

    def add_breakpoint(self, row):
        if not row in self.breaks:
            self.breaks[row] = {}
            if protocol and protocol.connected:
                protocol.send('breakpoint_set', t='line', f=self.uri(), n=row)
                res = protocol.read().firstChild
                self.breaks[row]['id'] = res.getAttribute('id')

    def del_breakpoint(self, row):
        if row in self.breaks:
            if protocol and protocol.connected:
                protocol.send('breakpoint_remove', d=self.breaks[row]['id'])
            del self.breaks[row]

    def view_breakpoints(self):
        self.view.add_regions('xdebug_breakpoint', self.lines(self.breaks.keys()), get_setting('breakpoint_scope'), breakpoint_icon, sublime.HIDDEN)

    def breakpoint_init(self):
        if not self.breaks:
            return
        uri = self.uri()
        for row in self.breaks:
            protocol.send('breakpoint_set', t='line', f=uri, n=row)
            res = protocol.read().firstChild
            self.breaks[row]['id'] = res.getAttribute('id')

    def breakpoint_clear(self):
        if not self.breaks:
            return
        for row in self.breaks.keys():
            self.del_breakpoint(row)

    def uri(self):
        return 'file://' + os.path.realpath(self.view.file_name())

    def lines(self, data=None):
        lines = []
        if data is None:
            regions = self.view.sel()
        else:
            if type(data) != types.ListType:
                data = [data]
            regions = []
            for item in data:
                if type(item) == types.IntType or item.isdigit():
                    regions.append(self.view.line(self.view.text_point(int(item) - 1, 0)))
                else:
                    regions.append(item)
        for region in regions:
            lines.extend(self.view.split_by_newlines(region))
        return [self.view.line(line) for line in lines]

    def rows(self, lines):
        if not type(lines) == types.ListType:
            lines = [lines]
        return [self.view.rowcol(line.begin())[0] + 1 for line in lines]

    def append(self, content, edit=None, end=False):
        if not edit:
            edit = self.view.begin_edit()
            end = True
        self.view.insert(edit, self.view.size(), content + "\n")
        if end:
            self.view.end_edit(edit)
        return edit

    def on_load(self):
        if self.current_line:
            self.current(self.current_line)
            self.current_line = None

    def current(self, line):
        if self.is_loading():
            self.current_line = line
            return
        region = self.lines(line)
        icon = current_icon

        if line in self.breaks.keys():
            icon = current_breakpoint_icon

        self.add_regions('xdebug_current_line', region, get_setting('current_line_scope'), icon, sublime.HIDDEN)
        self.center(line)

    def add_context_data(self, propName, propType, propData):
        '''
        Store context data
        '''
        self.context_data[propName] = {'type': propType, 'data': propData}

    def on_selection_modified(self):
        '''
        Show selected variable in an output panel when clicked
        '''
        if protocol and protocol.connected and self.context_data:
            data = ''
            point = self.view.sel()[0].a
            var_name = self.view.substr(self.view.word(point))
            if not var_name.startswith('$'):
                var_name = '$' + var_name
            is_variable = sublime.score_selector(self.view.scope_name(point), 'variable')

            if is_variable and var_name in self.context_data:
                kind = self.context_data[var_name]['type']
                if kind == 'array' or kind == 'object':
                    for key in sorted(self.context_data.keys()):
                        if key.startswith(var_name):
                            data += '{k} ({t}) = {d}\n'.format(k=key, t=self.context_data[key]['type'], d=self.context_data[key]['data'])
                else:
                    data += '{k} ({t}) = {d}\n'.format(k=var_name, t=kind, d=self.context_data[var_name]['data'])

            window = self.view.window()
            if window:
                output = window.get_output_panel('xdebug_inspect')
                edit = output.begin_edit()
                output.erase(edit, sublime.Region(0, output.size()))
                output.insert(edit, 0, data)
                output.end_edit(edit)
                window.run_command('show_panel', {"panel": 'output.xdebug_inspect'})


class XdebugListenCommand(sublime_plugin.TextCommand):
    '''
    Start listening for Xdebug connections
    '''
    def run(self, edit):
        global protocol
        protocol = Protocol()

        threading.Thread(target=self.thread_callback).start()

    def thread_callback(self):
        protocol.accept()
        if protocol and protocol.connected:
            sublime.set_timeout(self.gui_callback, 0)

    def gui_callback(self):
        sublime.status_message('Xdebug: Connected')
        init = protocol.read().firstChild
        uri = init.getAttribute('fileuri')
        #show_file(self.view.window(), uri)

        for view in buffers.values():
            view.breakpoint_init()

        self.view.run_command('xdebug_continue', {'state': 'run'})

    def is_enabled(self):
        if protocol:
            return False
        return True


class XdebugClearAllBreakpointsCommand(sublime_plugin.TextCommand):
    '''
    Clear breakpoints in all open buffers
    '''
    def run(self, edit):
        for view in buffers.values():
            view.breakpoint_clear()
            view.view_breakpoints()


class XdebugBreakpointCommand(sublime_plugin.TextCommand):
    '''
    Toggle a breakpoint
    '''
    def run(self, edit):
        view = lookup_view(self.view)
        for row in view.rows(view.lines()):
            if row in view.breaks:
                view.del_breakpoint(row)
            else:
                view.add_breakpoint(row)
        view.view_breakpoints()


class XdebugCommand(sublime_plugin.TextCommand):
    '''
    The Xdebug main quick panel menu
    '''
    def run(self, edit):
        mapping = {
            'xdebug_breakpoint': 'Add/Remove Breakpoint',
            'xdebug_clear_all_breakpoints': 'Clear all Breakpoints',
        }

        if protocol:
            mapping['xdebug_clear'] = 'Stop debugging'
        else:
            mapping['xdebug_listen'] = 'Start debugging'

        if protocol and protocol.connected:
            mapping.update({
                'xdebug_status': 'Status',
                'xdebug_execute': 'Execute',
            })

        self.cmds = mapping.keys()
        self.items = mapping.values()
        self.view.window().show_quick_panel(self.items, self.callback)

    def callback(self, index):
        if index == -1:
            return

        command = self.cmds[index]
        self.view.run_command(command)

        if protocol and command == 'xdebug_listen':
            url = get_project_setting('url')
            if url:
                webbrowser.open(url + '?XDEBUG_SESSION_START=sublime.xdebug')
            else:
                sublime.status_message('Xdebug: No URL defined in project settings file.')

            global original_layout
            global debug_view
            window = sublime.active_window()
            original_layout = window.get_layout()
            debug_view = window.active_view()
            window.set_layout({
                "cols": [0.0, 0.5, 1.0],
                "rows": [0.0, 0.7, 1.0],
                "cells": [[0, 0, 2, 1], [0, 1, 1, 2], [1, 1, 2, 2]]
            })

        if command == 'xdebug_clear':
            url = get_project_setting('url')
            if url:
                webbrowser.open(url + '?XDEBUG_SESSION_STOP=sublime.xdebug')
            else:
                sublime.status_message('Xdebug: No URL defined in project settings file.')
            window = sublime.active_window()
            window.run_command('hide_panel', {"panel": 'output.xdebug_inspect'})
            window.set_layout(original_layout)


class XdebugContinueCommand(sublime_plugin.TextCommand):
    '''
    Continue execution menu and commands.

    This command shows the quick panel and executes the selected option.
    '''
    states = {
        'run': 'Run',
        'step_into': 'Step Into',
        'step_over': 'Step Over',
        'step_out': 'Step Out',
        'stop': 'Stop',
        'detach': 'Detach',
    }

    def run(self, edit, state=None):
        if not state or not state in self.states:
            self.view.window().show_quick_panel(self.states.values(), self.callback)
        else:
            self.callback(state)

    def callback(self, state):
        if state == -1:
            return
        if type(state) == int:
            state = self.states.keys()[state]

        global xdebug_current
        reset_current()

        protocol.send(state)
        res = protocol.read().firstChild

        for child in res.childNodes:
            if child.nodeName == 'xdebug:message':
                #print '>>>break ' + child.getAttribute('filename') + ':' + child.getAttribute('lineno')
                sublime.status_message('Xdebug: breakpoint')
                xdebug_current = show_file(self.view.window(), child.getAttribute('filename'))
                xdebug_current.current(int(child.getAttribute('lineno')))

        if (res.getAttribute('status') == 'break'):
            # TODO stack_get
            protocol.send('context_get')
            res = protocol.read().firstChild
            result = ''

            def getValues(node):
                result = unicode('')
                for child in node.childNodes:
                    if child.nodeName == 'property':
                        propName = unicode(child.getAttribute('fullname'))
                        propType = unicode(child.getAttribute('type'))
                        propValue = None
                        try:
                            propValue = unicode(' '.join(base64.b64decode(t.data) for t in child.childNodes if t.nodeType == t.TEXT_NODE or t.nodeType == t.CDATA_SECTION_NODE))
                        except:
                            propValue = unicode(' '.join(t.data for t in child.childNodes if t.nodeType == t.TEXT_NODE or t.nodeType == t.CDATA_SECTION_NODE))
                        if propName:
                            if propName.lower().find('password') != -1:
                                propValue = unicode('*****')
                            result = result + unicode(propName + ' [' + propType + '] = ' + str(propValue) + '\n')
                            result = result + getValues(child)
                            if xdebug_current:
                                xdebug_current.add_context_data(propName, propType, propValue)
                return result

            result = getValues(res)
            add_debug_info('context', result)
            if xdebug_current:
                xdebug_current.on_selection_modified()

            protocol.send('stack_get')
            res = protocol.read().firstChild
            result = unicode('')
            for child in res.childNodes:
                if child.nodeName == 'stack':
                    propWhere = child.getAttribute('where')
                    propLevel = child.getAttribute('level')
                    propType = child.getAttribute('type')
                    propFile = child.getAttribute('filename')
                    propLine = child.getAttribute('lineno')
                    result = result + unicode('{level:>3}: {type:<10} {where:<10} {filename}:{lineno}\n' \
                                              .format(level=propLevel, type=propType, where=propWhere, lineno=propLine, filename=propFile))
            add_debug_info('stack', result)

        if res.getAttribute('status') == 'stopping' or res.getAttribute('status') == 'stopped':
            self.view.run_command('xdebug_clear')
            self.view.run_command('xdebug_listen')
            sublime.status_message('Xdebug: Page finished executing. Reload to continue debugging.')

    def is_enabled(self):
        if protocol and protocol.connected:
            return True
        if protocol:
            sublime.status_message('Xdebug: Waiting for executing to start')
            return False
        sublime.status_message('Xdebug: Not running')
        return False


class XdebugClearCommand(sublime_plugin.TextCommand):
    '''
    Close the socket and stop listening to xdebug
    '''
    def run(self, edit):
        global protocol
        try:
            protocol.clear()
            reset_current()
        except:
            pass
        finally:
            protocol = None

    def is_enabled(self):
        if protocol:
            return True
        return False


class XdebugStatus(sublime_plugin.TextCommand):
    '''
    DBGp status command
    '''
    def run(self, edit):
        protocol.send('status')
        res = protocol.read().firstChild
        sublime.status_message(res.getAttribute('reason') + ': ' + res.getAttribute('status'))

    def is_enabled(self):
        if protocol and protocol.connected:
            return True
        return False


class XdebugExecute(sublime_plugin.TextCommand):
    '''
    Execute arbitrary DBGp command
    '''
    def run(self, edit):
        self.view.window().show_input_panel('Xdebug Execute', '',
            self.on_done, self.on_change, self.on_cancel)

    def is_enabled(self):
        if protocol and protocol.connected:
            return True
        return False

    def on_done(self, line):
        if ' ' in line:
            command, args = line.split(' ', 1)
        else:
            command, args = line, ''
        protocol.send(command, args)
        res = protocol.read().firstChild

        window = self.view.window()
        output = window.get_output_panel('xdebug_execute')
        edit = output.begin_edit()
        output.erase(edit, sublime.Region(0, output.size()))
        output.insert(edit, 0, res.toprettyxml())
        output.end_edit(edit)
        window.run_command('show_panel', {"panel": 'output.xdebug_execute'})

    def on_change(self, line):
        pass

    def on_cancel(self):
        pass


class EventListener(sublime_plugin.EventListener):
    def on_new(self, view):
        lookup_view(view).on_new()

    def on_clone(self, view):
        lookup_view(view).on_clone()

    def on_load(self, view):
        lookup_view(view).on_load()

    def on_close(self, view):
        lookup_view(view).on_close()

    def on_pre_save(self, view):
        lookup_view(view).on_pre_save()

    def on_post_save(self, view):
        lookup_view(view).on_post_save()

    def on_modified(self, view):
        lookup_view(view).on_modified()

    def on_selection_modified(self, view):
        lookup_view(view).on_selection_modified()

    def on_activated(self, view):
        lookup_view(view).on_activated()

    def on_deactivated(self, view):
        lookup_view(view).on_deactivated()

    def on_query_context(self, view, key, operator, operand, match_all):
        lookup_view(view).on_query_context(key, operator, operand, match_all)


def lookup_view(v):
    '''
    Convert a Sublime View into an XdebugView
    '''
    if isinstance(v, XdebugView):
        return v
    if isinstance(v, sublime.View):
        id = v.buffer_id()
        if id in buffers:
            buffers[id].view = v
        else:
            buffers[id] = XdebugView(v)
        return buffers[id]
    return None


def show_file(window, uri):
    '''
    Open or focus a window
    '''
    if window:
        window.focus_group(0)
    if sublime.platform() == 'windows':
        transport, filename = uri.split(':///', 1)  # scheme:///C:/path/file => scheme, C:/path/file
    else:
        transport, filename = uri.split('://', 1)  # scheme:///path/file => scheme, /path/file
    if transport == 'file' and os.path.exists(filename):
        window = sublime.active_window()
        views = window.views()
        found = False
        for v in views:
            if v.file_name():
                path = os.path.realpath(v.file_name())
                if path == os.path.realpath(filename):
                    view = v
                    window.focus_view(v)
                    found = True
                    break
        if not found:
            #view = window.open_file(filename, sublime.TRANSIENT)
            view = window.open_file(filename)
        return lookup_view(view)


def reset_current():
    '''
    Reset the current line marker
    '''
    global xdebug_current
    if xdebug_current:
        xdebug_current.erase_regions('xdebug_current_line')
        xdebug_current = None


def get_project_setting(key):
    '''
    Get a project setting.

    Xdebug project settings are stored in the sublime project file
    as a dictionary:

        "settings":
        {
            "xdebug": { "key": "value", ... }
        }
    '''
    try:
        s = sublime.active_window().active_view().settings()
        xdebug = s.get('xdebug')
        if xdebug:
            if key in xdebug:
                return xdebug[key]
    except:
        pass


def get_setting(key):
    '''
    Get Xdebug setting
    '''
    s = sublime.load_settings("Xdebug.sublime-settings")
    if s and s.has(key):
        return s.get(key)


def add_debug_info(name, data):
    '''
    Adds data to the debug output windows
    '''
    found = False
    v = None
    window = sublime.active_window()

    if name == 'context':
        group = 1
        fullName = "Xdebug Context"
    if name == 'stack':
        group = 2
        fullName = "Xdebug Stack"

    for v in window.views():
        if v.name() == fullName:
            found = True
            break

    if not found:
        v = window.new_file()
        v.set_scratch(True)
        v.set_read_only(True)
        v.set_name(fullName)
        v.settings().set('word_wrap', False)
        found = True

    if found:
        v.set_read_only(False)
        window.set_view_index(v, group, 0)
        edit = v.begin_edit()
        v.erase(edit, sublime.Region(0, v.size()))
        v.insert(edit, 0, data)
        v.end_edit(edit)
        v.set_read_only(True)

    window.focus_group(0)
