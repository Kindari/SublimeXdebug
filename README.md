# SublimeXdebug

Simple client to connect with Xdebug.

Use `cmd+shift+t` in mac, or `win+shift+t` in windows/linux to show a list of actions:

- **Listen**: Start listening for an xdebug connection
- **Add/Remove Breakpoint**: A marker in the gutter shows the breakpoint

Once the xdebug connection is captured, using the same shortcut shows these xdebug actions:

- **Continue**: Shows the debugger control menu (see below)
- **Clear**: Stop listening
- **Add/remove breakpoint**
- **Status**: Shows the client status in the status bar

Debugger control menu:

- **Run**
- **Step Over**
- **Step Out**
- **Step Into**
- **Stop**
- **Detach**

## Troubleshooting

In ubuntu you might need to do:

    $ sudo apt-get install python2.6
    $ ln -s /usr/lib/python2.6 [Sublime Text dir]/lib/

