#!/usr/bin/env python

# trac-post-commit-hook
# ----------------------------------------------------------------------------
# Copyright (c) 2004 Stephen Hansen 
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to
# deal in the Software without restriction, including without limitation the
# rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
# sell copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
#   The above copyright notice and this permission notice shall be included in
#   all copies or substantial portions of the Software. 
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
# IN THE SOFTWARE.
# ----------------------------------------------------------------------------

# This Subversion post-commit hook script is meant to interface to the
# Trac (http://www.edgewall.com/products/trac/) issue tracking/wiki/etc 
# system.
# 
# It should be called from the 'post-commit' script in Subversion, such as
# via:
#
# REPOS="$1"
# REV="$2"
# TRAC_ENV='/somewhere/trac/project/'
#
# /usr/bin/python /usr/local/src/trac/contrib/trac-post-commit-hook \
#  -p "$TRAC_ENV"  \
#  -r "$REV"       
#
# It searches commit messages for text in the form of:
#   command #1
#   command #1, #2
#   command #1 & #2 
#   command #1 and #2
#
# You can have more then one command in a message. The following commands
# are supported. There is more then one spelling for each command, to make
# this as user-friendly as possible.
#
#   closes, fixes
#     The specified issue numbers are closed with the contents of this
#     commit message being added to it. 
#   references, refs, addresses, re 
#     The specified issue numbers are left in their current status, but 
#     the contents of this commit message are added to their notes. 
#
# A fairly complicated example of what you can do is with a commit message
# of:
#
#    Changed blah and foo to do this or that. Fixes #10 and #12, and refs #12.
#
# This will close #10 and #12, and add a note to #12.

import re
import os
import sys
from datetime import datetime 

from trac.env import open_environment
from trac.ticket.notification import TicketNotifyEmail
from trac.ticket import Ticket
from trac.ticket.web_ui import TicketModule
# TODO: move grouped_changelog_entries to model.py
from trac.util.datefmt import utc
from trac.versioncontrol.api import NoSuchChangeset

from optparse import OptionParser

parser = OptionParser()
parser.add_option('-p', '--project', dest='project', help='Path to the Trac project.')
parser.add_option('-r', '--revision', dest='rev', help='Repository revision number.')

(options, args) = parser.parse_args(sys.argv[1:])

leftEnv = ''
rghtEnv = ''
commandPattern = re.compile(leftEnv + r'(?P<action>[A-Za-z]*).?(?P<ticket>#[0-9]+(?:(?:[, &]*|[ ]?and[ ]?)#[0-9]+)*)' + rghtEnv)
ticketPattern = re.compile(r'#([0-9]*)')

# Old commands:
#	                    'close':      '_cmdClose',
#                       'closed':     '_cmdClose',
#                       'closes':     '_cmdClose',
#                       'fix':        '_cmdClose',
#                       'fixed':      '_cmdClose',
#                       'fixes':      '_cmdClose',
#                       'addresses':  '_cmdRefs',
#                       'references': '_cmdRefs',
#                       'see':        '_cmdRefs'}

class CommitHook:

    _supported_cmds = {
                       're':         '_cmdRefs',
                       'refs':       '_cmdRefs',
                       'qa':         '_cmdQa'
                      }

    def __init__(self, project=options.project, rev=options.rev):
        self.env = open_environment(project)
        repos = self.env.get_repository()
        repos.sync()

        # Instead of bothering with the encoding, we'll use unicode data
        # as provided by the Trac versioncontrol API (#1310).
        try:
            chgset = repos.get_changeset(rev)
        except NoSuchChangeset:
            return # out of scope changesets are not cached
        self.author = chgset.author
        self.rev = rev
        self.msg = "(In [%s]) %s" % (rev, chgset.message)
        self.now = datetime.now(utc)

        cmdGroups = commandPattern.findall(self.msg)

        tickets = {}
        for cmd, tkts in cmdGroups:
            funcname = CommitHook._supported_cmds.get(cmd.lower(), '')
            if funcname:
                for tkt_id in ticketPattern.findall(tkts):
                    func = getattr(self, funcname)
                    tickets.setdefault(tkt_id, []).append(func)

        for tkt_id, cmds in tickets.iteritems():
            try:
                db = self.env.get_db_cnx()

                ticket = Ticket(self.env, int(tkt_id), db)
                for cmd in cmds:
                    cmd(ticket)

                # determine sequence number... 
                cnum = 0
                tm = TicketModule(self.env)
                for change in tm.grouped_changelog_entries(ticket, db):
                    if change['permanent']:
                        cnum += 1

                ticket.save_changes(self.author, self.msg, self.now, db, cnum+1)
                db.commit()

                tn = TicketNotifyEmail(self.env)
                tn.notify(ticket, newticket=0, modtime=self.now)
            except Exception, e:
                # import traceback
                # traceback.print_exc(file=sys.stderr)
                print>>sys.stderr, 'Unexpected error while processing ticket ' \
                                   'ID %s: %s' % (tkt_id, e)

    def _cmdClose(self, ticket):
        ticket['status'] = 'closed'
        ticket['resolution'] = 'fixed'

    def _cmdRefs(self, ticket):
        pass

    def _cmdQa(self, ticket):
        ticket['phase'] = 'QA'
        ticket['owner'] = ''
        ticket['status'] = 'new'

if __name__ == "__main__":
    if len(sys.argv) < 5:
        print "For usage: %s --help" % (sys.argv[0])
        print
        print "Note that the deprecated options will be removed in Trac 0.12."
    else:
        CommitHook()
