import curses, re, socket, select, signal

PAD_HEIGHT = 350
PAD_WIDTH = 250

class Client(object):
    def __init__(self):
        self.attr = 0
        self.color = 0
        self.line_length = 0
        self.fg_color = 0
        self.bg_color = 0
        self.ansi_codes = re.compile('\x1B\\[(.*?)([a-zA-Z])')
        self.telnet_protocol = re.compile('\xFF([\xFB-\xFE].|[\xF0-\xFA])', re.S)
        self.ansi_attr_map = {
            1: lambda attr: attr | curses.A_BOLD,
            4: lambda attr: attr | curses.A_UNDERLINE,
            5: lambda attr: attr | curses.A_BLINK,
            7: lambda attr: attr | curses.A_REVERSE,
            22: lambda attr: attr & ~curses.A_BOLD,
            24: lambda attr: attr & ~curses.A_UNDERLINE,
            25: lambda attr: attr & ~curses.A_BLINK,
            27: lambda attr: attr & ~curses.A_REVERSE,
        }
        self.outbuf = ''
        self.inbuf = ''

    def parse_ansi(self, type, codes):
        if type == 'J':
            self.main_window.erase()
        elif type == 'm':
            for code in [int(c) for c in codes.split(';') if c.isdigit()]:
                if code in self.ansi_attr_map:
                    self.attr = self.ansi_attr_map[code](self.attr)
                elif code == 0:
                    self.attr = 0
                    self.fg_color = 0
                    self.bg_color = 0
                elif code / 10 == 3:
                    self.fg_color = code - 30
                elif code / 10 == 4:
                    self.bg_color = code - 40
            self.color = curses.color_pair(self.fg_color * 8 + self.bg_color)

    def _addstr(self, str):
        if str.endswith('\n'):
            self.line_length = 0
        else:
            self.line_length += len(str)
        self.main_window.addstr(str, self.color | self.attr)

    def word_wrap(self, text):
        width = self.width - 5
        while self.line_length + len(text) > width:
            split = text.rfind(' ', 0, width - self.line_length)
            if split < width - 20:
                split = width - self.line_length
            self._addstr(text[:split] + '\n')
            text = '  ' + (text[split:].lstrip())
        self._addstr(text)

    def display_text(self, text):
        text = self.telnet_protocol.sub('', text)
        while text:
            line, partition, text = text.partition('\n')
            left = 0
            for m in self.ansi_codes.finditer(line):
                self.word_wrap(line[left:m.start()])
                self.parse_ansi(m.group(2), m.group(1))
                left = m.end()
            self.word_wrap(line[left:])
            self._addstr(partition)

    def display(self, text):
        self.inbuf = (self.inbuf + text)[-10000:]
        text = self.telnet_protocol.sub('', text)
        self.display_text(text)

    def screen_setup(self):
        curses.start_color()
        curses.noecho()
        curses.cbreak()
        curses.nl()

        self.prompt = curses.newpad(1, 1024)
        self.prompt.move(0, 0)
        self.prompt.keypad(1)
        self.prompt.nodelay(1)

        self.main_window = curses.newwin(self.height - 2, self.width - 1, 0, 0)
        self.main_window.leaveok(1)
        self.main_window.scrollok(1)
        self.main_window.idlok(1)

        for fg in xrange(8):
            for bg in xrange(8):
                if fg or bg:
                    curses.init_pair(fg * 8 + bg, fg, bg)

        self.status = curses.newpad(1, self.width)
        self.status.bkgd('_', curses.color_pair(36))
        self.status.noutrefresh(0, 0, self.height - 2, 0, self.height - 1, self.width - 1)

    def poll(self, timeout=0.01):
        oready = self.outbuf and [self.sock] or []
        try:
            iready, oready, exc = select.select([self.sock], oready, [], timeout)
            if self.sock in oready:
                self.sock.sendall(self.outbuf)
                self.outbuf = ''
            if self.sock in iready:
                return self.sock.recv(4096)
        # survive interruptions from SIGWINCH
        except select.error:
            pass
        return ''

    def main(self, stdscr):
        self.height, self.width = stdscr.getmaxyx()
        self.screen_setup()
        self.display("\n\x1B[1;31mPyChor MUD Client\x1B[0m\n")
        self.sock = socket.socket()
        self.sock.connect(('divineblood.org', 4000))
        while True:
            curses.doupdate()
            self.display(self.poll(0.05))
            key = self.prompt.getch()
            if key == curses.KEY_RESIZE:
                old_height, old_width = self.height, self.width
                self.height, self.width = stdscr.getmaxyx()
                new_main_window = curses.newwin(self.height - 2, self.width - 1, 0, 0)
                new_main_window.leaveok(1)
                new_main_window.scrollok(1)
                new_main_window.idlok(1)
                self.main_window.erase()
                self.main_window = new_main_window
                self.display_text(self.inbuf[-(self.width * self.height):])
                self.status.noutrefresh(0, 0, self.height - 2, 0, self.height - 1, self.width - 1)
            self.main_window.noutrefresh()
            self.prompt.noutrefresh(0, 0, self.height - 1, 0, self.height, self.width - 1)
            if key < 0:
                continue
            cursor_y, cursor_x = self.prompt.getyx()
            if key >= 30 and key <= 127:
                self.prompt.insstr(chr(key))
                self.prompt.move(cursor_y, cursor_x + 1)
            elif key == curses.KEY_UP:
                pass
                #up through buffer
            elif key == curses.KEY_DOWN:
                pass
                #down through buffer
            elif key == curses.KEY_BACKSPACE and cursor_x > 0:
                self.prompt.move(cursor_y, cursor_x - 1)
                self.prompt.delch()
            elif key == curses.KEY_LEFT and cursor_x > 0:
                self.prompt.move(cursor_y, cursor_x - 1)
            elif key == curses.KEY_RIGHT:
                self.prompt.move(cursor_y, cursor_x + 1)
            elif key == 21: # ^U
                self.prompt.erase()
            elif key == curses.KEY_ENTER or key == 10:
                for command in self.prompt.instr(0, 0, 1024).strip().split(';'):
                    self.display("\x1B[1;33m%s\x1B[0m\n" % command.strip())
                    self.outbuf += "%s\n\r" % command.strip()
                self.prompt.erase()

curses.wrapper(Client().main)

