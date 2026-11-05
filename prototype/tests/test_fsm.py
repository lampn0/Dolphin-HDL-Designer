"""Regression tests for the FSM prototype.

Run from the prototype folder:  python -m unittest discover tests
The golden test needs the legacy sample files; point DHDS_SAMPLES at the
folder holding fsm.sm and gc_control_fsm.v (default: D:/workspace).
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dhds.codegen import fsm_codegen  # noqa: E402
from dhds.codegen.encoding import encode  # noqa: E402
from dhds.codegen.fsm_codegen import assignment_target, generate, split_statements  # noqa: E402
from dhds.examples import traffic_light  # noqa: E402
from dhds.hds.import_sm import import_sm  # noqa: E402
from dhds.model import FsmView  # noqa: E402

SAMPLES = os.environ.get('DHDS_SAMPLES', 'D:/workspace')
SM = os.path.join(SAMPLES, 'fsm.sm')
GOLDEN = os.path.join(SAMPLES, 'gc_control_fsm.v')


def _body(text: str) -> str:
    """From '// State encoding' to the end: the part not affected by header/ports."""
    return text[text.index('// State encoding'):]


class TestStatements(unittest.TestCase):
    def test_split_keeps_if_else_together(self):
        s = split_statements("a <= 1;\nif (x) begin\n  b = 2;\nend\nelse\n  c = 3;\nd <= 4; // tail")
        self.assertEqual(len(s), 3)
        self.assertTrue(s[1].startswith('if (x)') and 'else' in s[1])
        self.assertTrue(s[2].endswith('// tail'))

    def test_target_skips_comparisons(self):
        self.assertEqual(assignment_target('if (a <= b) y_cld <= 1;'), ('y_cld', '<='))
        self.assertEqual(assignment_target('{p, q} = 2\'b01;'), ('p', '='))


class TestEncoding(unittest.TestCase):
    def test_styles(self):
        names = ['A', 'B', 'C', 'D']
        self.assertEqual(encode(names, 'sequential')[1]['D'], "2'd3")
        self.assertEqual(encode(names, 'gray')[1]['D'], "2'b10")
        self.assertEqual(encode(names, 'onehot')[1]['C'], "4'b0100")
        self.assertEqual([v for v in encode(names, 'johnson')[1].values()], ["2'b00", "2'b10", "2'b11", "2'b01"])


class TestExample(unittest.TestCase):
    def test_json_round_trip(self):
        v = traffic_light()
        v2 = FsmView.from_json(v.to_json())
        self.assertEqual(generate(v)[0], generate(v2)[0])

    def test_all_options_generate(self):
        v = traffic_light()
        for lang in ('verilog', 'systemverilog'):
            for decl in ('parameter', 'localparam', 'enum'):
                v.language, v.machines[0].state_decl = lang, decl
                text, warnings = generate(v)
                self.assertIn('endmodule', text)
                if lang == 'systemverilog':
                    self.assertIn('always_ff', text)
                    self.assertEqual(warnings, [])
                if decl == 'enum' and lang == 'systemverilog':
                    self.assertIn('typedef enum logic', text)


@unittest.skipUnless(os.path.exists(SM) and os.path.exists(GOLDEN), 'legacy samples not found')
class TestLegacyGolden(unittest.TestCase):
    def test_body_matches_legacy_tool(self):
        # the legacy golden was generated with "Allow implicit event expression (@*)" set
        view = import_sm(SM, library='protocol_controller', unit='gc_control_fsm')
        saved, fsm_codegen.IMPLICIT_EVENT = fsm_codegen.IMPLICIT_EVENT, True
        try:
            text, warnings = generate(view, 'verilog')
        finally:
            fsm_codegen.IMPLICIT_EVENT = saved
        self.assertEqual(warnings, [])
        with open(GOLDEN, encoding='utf-8') as f:
            golden = f.read()
        self.assertEqual(_body(text), _body(golden))

    def test_systemverilog_compiles(self):
        try:
            import pyslang
            from pyslang.ast import Compilation
            from pyslang.syntax import SyntaxTree
        except ImportError:
            self.skipTest('pyslang not installed')
        view = import_sm(SM, library='protocol_controller', unit='gc_control_fsm')
        stub = ''.join(f"localparam {n} = 5'd{i};\n" for i, n in enumerate(
            'MC_CMD_DES MC_CMD_IDLE MC_CMD_PDE MC_CMD_PDX MC_CMD_REFA MC_CMD_SRE MC_CMD_SRX MC_CMD_MRS '
            'USER_CMD_STOP USER_CMD_RUN USER_CMD_SRE USER_CMD_SRX USER_CMD_PDE USER_CMD_PDX USER_CMD_MRS'.split()))
        for decl in ('parameter', 'localparam', 'enum'):
            view.machines[0].state_decl = decl
            text, _ = generate(view, 'systemverilog')
            text = re.sub(r'^\s*`include.*$', '', text, flags=re.M)
            text = re.sub(r'`CFG_\w+', '8', text).replace('// Internal Declarations', stub, 1)
            comp = Compilation()
            comp.addSyntaxTree(SyntaxTree.fromText(text))
            errors = [d for d in comp.getAllDiagnostics() if d.isError()]
            self.assertEqual(errors, [], pyslang.DiagnosticEngine.reportAll(comp.sourceManager, errors))


if __name__ == '__main__':
    unittest.main()
