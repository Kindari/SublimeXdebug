import sublime, sublime_plugin
import os
import socket
import base64
import threading
import Queue
import types
import time
from functools import partial
from xml.dom.minidom import parseString

layout = {
	'rows': [0.0, 0.75, 1.0],
	'cols': [0.0, 0.5, 1.0],
	'cells': [[0, 0, 2, 1], [0, 1, 1, 2], [1, 1, 2, 2]],
}


class DebuggerException(Exception): pass
class ProtocolException(DebuggerException): pass
class ProtocolConnectionException(ProtocolException): pass

class Protocol(object):
	"""Represents DBGp Protocol Language"""

	read_rate = 1024
	port = 9000

	def __init__(self):
		self.clear()

	def clear(self):
		self.buffer = ''
		self.connected = False
		self.listening = False
		self.server = None
		self.contexts = ContextManager()
		del self.transaction_id
		try:
			self.sock.close()
		except:
			pass
		self.sock = None

	def transaction_id():
	    doc = "The transaction_id property."
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
			if '\x00' in self.buffer:
				data, self.buffer = self.buffer.split('\x00', 1)
				return data
			else:
				self.buffer += self.sock.recv( self.read_rate )
				return self.read_until_null()
		else:
			raise ProtocolConnectionException, "Not Connected"

	def read_data(self):
		length = self.read_until_null()
		message = self.read_until_null()
		if int(length)==len(message):
			return message
		else:
			raise ProtocolException, "Length mismatch"

	def read(self):
		data = self.read_data()
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

		if args: parts.extend( args )
		if kwargs: parts.extend(['-%s %s' % pair for pair in kwargs.items()])
		parts = [part.strip() for part in parts if part.strip()]
		command = ' '.join(parts)
		if data: command += ' -- ' + base64.b64encode( data )

		try:
			self.sock.send( command + '\x00' )
			print "--->", `command`
		except Exception, x:
			print command
			raise ProtocolConnectionException, x

	def accept(self):
		serv = socket.socket( socket.AF_INET, socket.SOCK_STREAM )
		serv.setsockopt( socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
		serv.settimeout(1)
		serv.bind( ('', self.port ))
		serv.listen(1)
		self.listening = True
		while self.listening:
			try:
				self.sock, address = serv.accept()
				print self.sock, address
				self.listening = False
			except socket.timeout:
				pass

		self.connected = True
		self.sock.settimeout(None)
		try:
			serv.close()
			serv = None
		except:
			pass
		return self.sock

class ContextManager(object):
	def __init__(self):
		self.contexts = {}
	def update(self):
		if protocol.connected:
			protocol.send('context_names')
			res = protocol.read().firstChild
			for child in res.childNodes:
				name = child.getAttribute('name')
				id = child.getAttribute('id')
				if not id in self.contexts:
					self.contexts[id] = Context(id, name, self)


class Context(object):
	def __init__(self, id, name, manager):
		self.id = id
		self.name = name
		self.manager = manager
		self.properties = []
		self.get()
		print self.properties
	def get(self):
		protocol.send('context_get', c=self.id)
		res = protocol.read().firstChild
		for child in res.childNodes:
			prop = Property(child, self)
			self.properties.append(prop)

class Property(object):
	def __init__(self, res, parent = None):
		self.raw = res
		self.parent = parent
		self.children = []
		self.attributes = {}
		if res.attributes:
			for key, value in res.attributes.items():
				self.attributes[key] = value
		for child in res.childNodes:
			self.children.append( Property(child, self) )
	def __repr__(self):
		attr = self.attributes
		if attr['type']=='array':
			return "%s (%d)[...]" % ( attr['name'], attr['numchildren'] )
		return 'UnImplemented'


protocol = None

class XdebugView(object):
	def __init__(self, view):
		self.view = view
		self.breaks = { } # line : meta { id: bleh } 
	def __getattr__(self, attr):
		if hasattr(self.view, attr):
			return getattr(self.view, attr)
		raise AttributeError, "%s does not exist" % attr
	def center(self, lineno):
		line = self.lines(lineno)[ 0 ]
		self.view.show_at_center( line )
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
				print protocol.read().firstChild.toprettyxml()
			del self.breaks[row]

	def view_breakpoints(self):
		self.view.add_regions('dbgp_breakpoints',
			self.lines(self.breaks.keys()), 'dbgp.breakpoint', 'bookmark', sublime.HIDDEN)
	def breakpoint_init(self):
		uri = self.uri()
		for row in self.breaks:
			protocol.send('breakpoint_set', t='line', f=uri, n=row)
			res = protocol.read().firstChild
			self.breaks[row]['id'] = res.getAttribute('id')

	def uri(self):
		return 'file://' + self.view.file_name()

	def lines(self, data = None):
		lines = []
		if data is None:
			regions = self.view.sel()
		else:
			if type(data) != types.ListType:
				data = [data]
			regions = []
			for item in data:
				if type(item)==types.IntType or item.isdigit():
					regions.append( self.view.line( self.view.text_point( int(item)-1, 0) ) )
				else:
					regions.append( item )
		for region in regions:
			lines.extend(self.view.split_by_newlines(region))
		return [self.view.line(line) for line in lines]

	def rows(self, lines):
		if not type(lines)==types.ListType: lines = [lines]
		return [self.view.rowcol(line.begin())[0] + 1 for line in lines]
	def append(self, content, edit = None, end=False):
		if not edit:
			edit = self.view.begin_edit()
			end = True
		self.view.insert(edit, self.view.size(), content + "\n")
		if end:
			self.view.end_edit(edit)
		return edit

class XdebugCommand(sublime_plugin.TextCommand):
	def run(self, edit):
		mapping = {
			'xdebug_breakpoint' : 'Add/Remove Breakpoint',
		}
		if protocol:
			mapping['xdebug_clear'] = 'Clear'
			if protocol.connected:
				mapping.update( {
					'xdebug_continue'	: 'Continue',
					'xdebug_status'		: 'Status',
				})
		else:
			mapping['xdebug_listen'] = 'Listen'
		def callback(index):
			if index== -1: return
			command = cmds[index]
			self.view.run_command(command)
		cmds = mapping.keys()
		items = mapping.values()
		self.view.window().show_quick_panel(items, callback)



class XdebugListenCommand(sublime_plugin.TextCommand):
	def run(self, edit):
		global protocol
		protocol = Protocol()

		threading.Thread(target=self.thread_callback).start()

	def thread_callback(self):
		protocol.accept()
		if protocol and protocol.connected:
			sublime.set_timeout( self.gui_callback, 0)

	def gui_callback(self):
		init = protocol.read().firstChild
		uri = init.getAttribute('fileuri')
		show_file(self.view.window(), uri)

		for view in dbgviews.values():
			view.breakpoint_init()

	def is_enabled(self):
		if protocol:
			return False
		return True

class XdebugBreakpointCommand(sublime_plugin.TextCommand):
	def run(self, edit):
		view = lookup_view( self.view )
		for row in view.rows(view.lines()):
			if row in view.breaks:
				view.del_breakpoint(row)
			else:
				view.add_breakpoint(row)
		view.view_breakpoints()

class XdebugContinueCommand(sublime_plugin.TextCommand):
	states = {
		'run'		: 'Run',
		'step_into'	: 'Step Into',
		'step_over'	: 'Step Over',
		'step_out'	: 'Step Out',
		'stop'		: 'Stop',
		'detach'	: 'Detach',
	}
	def run(self, edit, state=None):
		if not state or not state in self.states:
			self.view.window().show_quick_panel( self.states.values(), self.callback)
		else:
			self.callback( state )
	def callback(self, state):
		if state==-1: return
		if type(state)==int:
			state = self.states.keys()[state]
		
		global xdebug_current, xdebug_current_line
		reset_current()

		protocol.send( state )
		res = protocol.read().firstChild
		print res.toprettyxml()

		for child in res.childNodes:
			if child.nodeName=='xdebug:message':
				xdebug_current_line = int(child.getAttribute('lineno'))
				xdebug_current = show_file(self.view.window(), child.getAttribute('filename') )
				print 'current', xdebug_current
				debug_line()

	def is_enabled(self):
		if protocol and protocol.connected:
			return True
		return False

class XdebugClearCommand(sublime_plugin.TextCommand):
	def run(self, edit):
		global protocol
		try:
			protocol.clear()
		except:
			pass
		finally:
			protocol = None
	def is_enabled(self):
		if protocol:
			return True
		return False

class XdebugStatus(sublime_plugin.TextCommand):
	def run(self, edit):
		protocol.send('status')
		res = protocol.read().firstChild
		sublime.set_status( res.getAttribute('reason') + ': ' + res.getAttribute('status') )

	def is_enabled(self):
		if protocol and protocol.connected:
			return True
		return False

class EventListener(sublime_plugin.EventListener):
	def on_load(self, view):
		if xdebug_current and not xdebug_current.is_loading():
			debug_line()
			xdebug_current.center( xdebug_current_line )



dbgviews = {}
dbguris = {}
def lookup_view(view):
	if not view in dbgviews:
		dbgviews[view] = XdebugView(view)
	return dbgviews[view]
def uri_view(uri):
	if uri in dbguris:
		return dbguris[uri]
	for view in dbgviews.values():
		if view.file_name()==uri:
			dbguris[uri] = view
			return view

def show_file( window, uri):
	transport, filename = uri.split('://', 1)
	if transport=='file' and os.path.exists(filename):
		view = window.open_file(filename, sublime.TRANSIENT)
		dbg_view = lookup_view(view)
		return dbg_view

xdebug_current = None
xdebug_current_line = None
def debug_line():
	if xdebug_current and xdebug_current.is_loading(): return
	if not xdebug_current_line: return 
	xdebug_current.add_regions( 'xdebug_current_line',
		xdebug_current.lines(xdebug_current_line), 
		'xdebug.current_line', 'circle', sublime.HIDDEN)

def reset_current():
	global xdebug_current, xdebug_current_line
	if xdebug_current:
		xdebug_current.erase_regions('xdebug_current_line')
		xdebug_current = None
		xdebug_current_line = None
