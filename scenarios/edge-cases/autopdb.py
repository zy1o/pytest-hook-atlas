"""A debugger that leaves as soon as it arrives.

pytest fires pytest_enter_pdb when --pdb drops into the debugger, and
pytest_leave_pdb from its wrapper around `do_continue`. Overriding `interaction`
to simply return would skip that wrapper and miss the second hook, so this goes
through do_continue properly - and the run finishes instead of waiting for a
terminal that is not there.
"""

import pdb


class AutoPdb(pdb.Pdb):
    def interaction(self, frame, traceback):
        self.setup(frame, traceback)
        self.do_continue("")
        self.forget()
