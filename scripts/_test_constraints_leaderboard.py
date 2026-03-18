"""Quick check: leaderboard-style prompts -> parsed constraints."""
from agent import _parse_task_constraints

SAMPLES = [
    "Show details for a movie where the genres field CONTAINS 'Romance', the rating field EQUALS '8.2', and the duration field is LESS THAN 126 minutes",
    "Collapse menu where the rating is GREATER THAN 3.5999999999999996 and the name does NOT CONTAIN 'wbnbqt'",
    "Mark unread where is_read equals 'False', from_email does NOT equal 'ashley.sanchez@offers.com'",
    "Open add-to-cart where price less equal '17.98' and restaurant equals 'Belcanto'",
]

for s in SAMPLES:
    c = _parse_task_constraints(s)
    print(s[:70] + "...")
    print([(x["field"], x["op"], str(x["value"])[:40]) for x in c])
    print()
