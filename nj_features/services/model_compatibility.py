"""Physical compatibility checks shared by the allocation paths.

Allocation may legitimately hand an order a machine that is not yet the item
the customer bought: the unit carries a ``to_make`` target and production
rebuilds it. That is how a 5420 TOUCH i7 64GB/1TB becomes a 5420 TOUCH i7
8GB/256GB - RAM and storage are swapped on the bench every day.

What production cannot do is change the screen. A Non-Touch (NT) panel and a
Touch (IR/digitiser) panel are different parts in a different chassis, so a
unit whose physical item is Non-Touch must never be allocated against a Touch
order, however its ``to_make`` reads.

``nj_production_planning._is_same_model_family`` already enforces this, but
only for Condition 3 (parent model + CPU), which is how a donor unit gets
*chosen*. Conditions 1b/2/4 match on ``to_make`` or on Shopify variant
grouping and never consult it, so a ``to_make`` written by any other route -
a manual edit, an older plan - is honoured without question. This module is
that missing check, applied centrally at the point of assignment.
"""

import re

# Screen-type markers as they appear in item codes, e.g.
#   S-Dell 5420 IR(40PIN NT)-CORE I7 ...   -> {'nt'}
#   S-Dell 5420 TOUCH(IR)-CORE I7 ...      -> {'touch'}
_TOUCH_SCREEN_MARKER_WORDS = {'touch', 'nt'}


def _screen_markers(item_code):
    """Return the screen-type markers present in an item code."""
    if not item_code:
        return set()
    tokens = re.findall(r'[a-z0-9]+', str(item_code).lower())
    return {t for t in tokens if t in _TOUCH_SCREEN_MARKER_WORDS}


def is_screen_type_compatible(physical_item_code, target_item_code):
    """False only when the two item codes carry CONFLICTING screen markers.

    Deliberately conservative: it blocks solely the unambiguous case where one
    side is explicitly Touch and the other explicitly NT. When either side
    carries no marker at all the pair is allowed through.

    That silence is common and does not reliably mean Non-Touch - plenty of
    Touch models are named without the word, e.g.
    ``S-Dell 5410(IR-KBD WTB)``. Refusing those would strand real stock and
    push orders onto the 47-day fallback SLA for a naming convention rather
    than a physical incompatibility. Tighten this only alongside a cleanup of
    the item naming, not before.
    """
    a = _screen_markers(physical_item_code)
    b = _screen_markers(target_item_code)
    if not a or not b:
        return True
    return a == b
