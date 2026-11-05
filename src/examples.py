"""Small example state machine used for File > New."""
from __future__ import annotations

from model import FsmView, Machine, Parameter, Point, Signal, State, Transition


def traffic_light() -> FsmView:
    """A three-state traffic light FSM (red -> green -> yellow, with a timer and a pedestrian
    request): the example opened by File > New and by bin/fsm_editor.py without arguments.
    """
    m = Machine(name='light_fsm')
    m.states = [
        State('s1', 'ST_RED', 0, 0, entry_actions="timer_cld <= RED_TIME;"),
        State('s2', 'ST_GREEN', 260, 0, entry_actions="timer_cld <= GREEN_TIME;"),
        State('s3', 'ST_YELLOW', 130, 200, entry_actions="timer_cld <= YELLOW_TIME;"),
    ]
    for s in m.states:
        s.in_actions = "timer_cld <= timer_cld - 1'b1;"
    m.points = [Point('p1', 'clock', -200, -120), Point('p2', 'reset', -200, -80),
                Point('p3', 'recovery', -200, 120)]
    m.transitions = [
        Transition('t1', 'p2', 's1'),
        Transition('t2', 's1', 's2', cond="timer_cld == 0", actions="go = 1'b1;"),
        Transition('t3', 's2', 's3', cond="timer_cld == 0 | ped_request"),
        Transition('t4', 's3', 's1', cond="timer_cld == 0"),
        Transition('t5', 'p3', 's1'),
    ]
    return FsmView(
        library='work', unit='traffic_light', view='fsm', language='systemverilog',
        parameters=[Parameter('RED_TIME', "8'd50"), Parameter('GREEN_TIME', "8'd40"),
                    Parameter('YELLOW_TIME', "8'd5")],
        signals=[
            Signal('clk', 'input', category='clock', expression='posedge clk', comment='System clock'),
            Signal('rst_n', 'input', category='reset', expression='!rst_n', comment='Async reset, active low'),
            Signal('ped_request', 'input', comment='Pedestrian button'),
            Signal('go', 'output', 'reg', scheme='comb', default="1'b0", comment='Pulse when light turns green'),
            Signal('timer', 'output', 'reg', bounds='[7:0]', scheme='clocked', reset="8'd0"),
        ],
        machines=[m],
    )
