"""Generates a personalized daily schedule from a predicted energy level
AND each user's individual habit profile.

The previous version produced one of three identical templates for every user
in the same energy bracket. This version personalises the schedule using:

  * Wake-up time inferred from the user's typical sleep duration
  * Work-block length scaled to the user's typical focus level
  * Break frequency scaled to the user's typical break minutes
  * Number of work blocks scaled to the user's typical tasks completed
  * A per-user-per-day random seed so two users with identical metrics still
    receive different (but stable for the day) task variations.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date as date_type
from typing import List, Tuple, Optional

from schemas import ScheduleTask


# --------------------------------------------------------------------------
#  User profile derived from recent history
# --------------------------------------------------------------------------

@dataclass
class UserProfile:
    """Simple averages of the user's recent productivity entries."""
    avg_sleep_hours: float = 7.5
    avg_focus_level: float = 6.0     # 1..10
    avg_tasks: float = 5.0
    avg_break_min: float = 45.0
    available_hours: float = 9.0
    user_id: int = 0


# --------------------------------------------------------------------------
#  Helpers
# --------------------------------------------------------------------------

def _classify_zone(energy: float) -> str:
    if energy >= 7:
        return "peak"
    if energy >= 4.5:
        return "moderate"
    return "low"


def _wake_hour_minute(avg_sleep_hours: float) -> Tuple[int, int]:
    """
    Heuristic: people who sleep more tend to wake later.
    6h sleep -> ~6:30 AM start, 7.5h -> 7:30, 9h -> 9:00.
    Clamp to a sensible 6:00-9:30 window.
    """
    base = 6.0 + (avg_sleep_hours - 6.0) * 0.6
    base = max(6.0, min(9.5, base))
    h = int(base)
    m = int(round((base - h) * 60))
    # Snap minutes to :00 / :15 / :30 / :45
    m = round(m / 15) * 15
    if m == 60:
        h, m = h + 1, 0
    return h, m


def _focus_block_minutes(avg_focus_level: float, energy_zone: str) -> int:
    """Higher focus + higher energy → longer deep-work blocks."""
    base = 30 + (avg_focus_level / 10.0) * 60   # 30..90 by focus
    if energy_zone == "peak":
        base += 15
    elif energy_zone == "low":
        base -= 15
    base = max(25, min(105, base))
    # Snap to nearest 5
    return int(round(base / 5) * 5)


def _short_break_minutes(avg_break_min: float) -> int:
    """Roughly 1/3 of avg total break time per micro-break, clamped 5..25."""
    val = max(5.0, min(25.0, avg_break_min / 3.0))
    return int(round(val / 5) * 5)


def _num_work_blocks(avg_tasks: float, available_hours: float, zone: str) -> int:
    """How many distinct work blocks to generate."""
    base = max(2, min(8, round(avg_tasks * 0.7)))
    if available_hours < 6:
        base = max(2, base - 1)
    elif available_hours >= 10:
        base += 1
    if zone == "low":
        base = max(2, base - 1)
    elif zone == "peak":
        base += 1
    return min(8, max(2, int(base)))


def _build_task_personalization_reason(
    *,
    task_type: str,
    title: str,
    start_min: int,
    duration: int,
    zone: str,
    predicted_energy: float,
    available_hours: float,
    profile: UserProfile,
    block_min: int,
    short_brk: int,
    lunch_start: int,
) -> str:
    """Explain how user data influenced a specific task."""
    profile_summary = (
        f"Uses your latest energy prediction ({predicted_energy:.1f}/10), "
        f"{available_hours:.1f} available hours, {profile.avg_sleep_hours:.1f} h average sleep, "
        f"{profile.avg_focus_level:.1f}/10 focus, ~{profile.avg_tasks:.0f} tasks per day, "
        f"and {profile.avg_break_min:.0f} average break minutes."
    )

    if task_type == "work":
        if start_min < lunch_start:
            window_reason = (
                "This focus block is placed earlier because that is your stronger work window for today's energy zone."
            )
        else:
            window_reason = (
                "This block is scheduled later in the day as a lighter follow-up that still fits your available hours."
            )
        return (
            f"{window_reason} The {duration}-minute length comes from your recent focus pattern, "
            f"which set today's focus blocks to about {block_min} minutes. {profile_summary}"
        )

    if task_type == "break":
        return (
            f"This recovery block was inserted between work sessions because your recent logs show a break rhythm "
            f"that maps to about {short_brk}-minute pauses. It helps the planner protect energy on a {zone} day. "
            f"{profile_summary}"
        )

    if task_type == "meal":
        return (
            f"This meal block is anchored around midday to keep your energy steady across a {available_hours:.1f}-hour day. "
            f"It sits between morning and afternoon work based on your available time and predicted energy. "
            f"{profile_summary}"
        )

    if task_type == "exercise":
        return (
            f"This movement block is added after lunch because the planner expects a post-lunch dip unless energy stays very high. "
            f"It is only included when there is enough room inside your available hours. {profile_summary}"
        )

    if title == "Gentle start":
        return (
            f"This softer opener appears because today's predicted energy is in the low zone, so the planner avoids heavy work immediately. "
            f"Your sleep and focus history are used to delay deeper work until later in the day. {profile_summary}"
        )

    return (
        f"This wrap-up block is added to close the day within your available hours and support recovery for tomorrow. "
        f"It reflects today's energy zone plus your recent sleep, focus, and workload patterns. {profile_summary}"
    )


# Pools of task titles + descriptions, varied by zone.
# A per-user RNG picks from these so different users get different wording.
_WORK_TITLES = {
    "peak": [
        ("Deep focus — hardest task", "Use your peak energy on the most demanding work."),
        ("Strategic thinking block",  "Architect, plan, or solve a complex problem."),
        ("High-leverage execution",   "Ship something that moves the needle today."),
        ("Critical project sprint",   "Single-task on your top priority — no context switches."),
        ("Creative problem solving",  "Tackle something requiring fresh ideas."),
        ("Senior-level review",       "Code review, document review, or quality pass."),
    ],
    "moderate": [
        ("Main focus block",          "Tackle your most important task at a steady pace."),
        ("Steady execution",          "Continue priority work — pace yourself."),
        ("Collaboration block",       "Meetings, pair work, async replies."),
        ("Project planning",          "Break down upcoming work into smaller chunks."),
        ("Email & inbox triage",      "Clear the inbox to free your mind."),
        ("Review & polish",           "Refine recent work; small wins compound."),
    ],
    "low": [
        ("Easy task block",           "Knock out small, low-effort tasks."),
        ("Admin & cleanup",           "File, archive, organise — low cognitive load."),
        ("Light reading & learning",  "Read a doc, watch a tutorial."),
        ("Calls & quick replies",     "Short-format work that doesn't need flow."),
        ("Notes & journaling",        "Capture thoughts; defer real work to tomorrow."),
        ("Tidy workspace",            "Reset your environment for tomorrow."),
    ],
}

_BREAK_VARIANTS = [
    ("Short break",          "Stretch and hydrate."),
    ("Movement break",       "Quick walk to maintain energy."),
    ("Active break",         "10 push-ups or a 2-min breathing exercise."),
    ("Coffee & stretch",     "Refill water, look out the window."),
    ("Step away",            "Leave your desk for 5 minutes."),
]

_LUNCH_VARIANTS = [
    ("Lunch",                "Balanced meal with protein and veggies."),
    ("Nourishing lunch",     "Whole foods — avoid heavy carbs to dodge the slump."),
    ("Lunch + walk",         "Eat, then 10-min walk outside if possible."),
]

_REST_VARIANTS = [
    ("Wind down",            "Plan tomorrow, reflect on today."),
    ("Reflection & planning","Review the day, set tomorrow's top 3."),
    ("Early wind down",      "Prep tomorrow, then prioritise sleep tonight."),
]

_EXERCISE_VARIANTS = [
    ("Movement",             "Light exercise or walk to recharge."),
    ("Energising movement",  "10–15 min walk to fight the afternoon dip."),
    ("Stretch session",      "Mobility work — neck, shoulders, hips."),
]


# --------------------------------------------------------------------------
#  Main entry point
# --------------------------------------------------------------------------

def generate_schedule(
    predicted_energy: float,
    available_hours: float,
    profile: Optional[UserProfile] = None,
    today: Optional[date_type] = None,
) -> Tuple[str, List[ScheduleTask], List[str], int, int]:
    """Returns (energy_zone, tasks, recommendations, work_min, break_min).

    `profile` carries the user's recent averages. If omitted, defaults are used.
    """
    if profile is None:
        profile = UserProfile(available_hours=available_hours)
    if today is None:
        today = date_type.today()

    zone = _classify_zone(predicted_energy)

    # Per-user-per-day deterministic RNG → stable schedule for the day,
    # but different from other users.
    seed = (profile.user_id * 1_000_003) + today.toordinal()
    rng = random.Random(seed)

    # --- Personalised parameters
    start_h, start_m = _wake_hour_minute(profile.avg_sleep_hours)
    # Add small per-user jitter to start time (-15..+15 min)
    jitter_min = rng.choice([-15, 0, 0, 15])
    start_total = start_h * 60 + start_m + jitter_min
    cursor = max(5 * 60 + 30, min(10 * 60, start_total))  # clamp 5:30..10:00

    block_min = _focus_block_minutes(profile.avg_focus_level, zone)
    short_brk = _short_break_minutes(profile.avg_break_min)
    n_blocks = _num_work_blocks(profile.avg_tasks, available_hours, zone)

    # --- Build the day
    plan: List[Tuple[int, int, str, str, str, str, str]] = []
    # (start_minute, duration, type, title, desc, energy_required, priority)

    work_pool = list(_WORK_TITLES[zone])
    rng.shuffle(work_pool)
    work_idx = 0

    # 1. Optional gentle start for low-energy days
    if zone == "low":
        plan.append((cursor, 25, "rest", "Gentle start",
                     "Light review of priorities. No heavy work yet.", "low", "low"))
        cursor += 25

    LUNCH_START = 12 * 60 + 30   # 12:30
    LUNCH_LATEST = 13 * 60 + 30  # 13:30

    # Targets are soft hints; we fill morning until we're close to lunch
    morning_blocks_target = max(1, n_blocks // 2)
    afternoon_blocks_target = max(1, n_blocks - morning_blocks_target)

    # 2. Morning focus blocks — keep packing blocks+breaks until we'd run past lunch.
    # We allow slightly OVER the soft target if there's still time before lunch,
    # because a long unfilled gap is worse than one extra block.
    morning_done = 0
    MORNING_MAX = 5  # safety cap
    while morning_done < MORNING_MAX and cursor + block_min <= LUNCH_LATEST:
        title, desc = work_pool[work_idx % len(work_pool)]
        work_idx += 1
        priority = "high" if morning_done == 0 else ("high" if zone == "peak" else "medium")
        energy_req = "high" if zone == "peak" else "medium"
        plan.append((cursor, block_min, "work", title, desc, energy_req, priority))
        cursor += block_min
        morning_done += 1
        # Stop if we've met target AND we're close enough to lunch (≤ short_brk + 10 min)
        if morning_done >= morning_blocks_target and (LUNCH_START - cursor) <= (short_brk + 10):
            break
        # Otherwise add a break IF another block can still fit before LUNCH_LATEST
        if cursor + short_brk + block_min <= LUNCH_LATEST:
            bt, bd = rng.choice(_BREAK_VARIANTS)
            plan.append((cursor, short_brk, "break", bt, bd, "low", "low"))
            cursor += short_brk
        else:
            break

    # 3. Lunch — at LUNCH_START or as soon as morning ends, whichever is later.
    # Any remaining gap becomes a single short break (capped at 25 min).
    lunch_at = max(LUNCH_START, cursor)
    if cursor < lunch_at:
        gap = min(25, lunch_at - cursor)
        bt, bd = rng.choice(_BREAK_VARIANTS)
        plan.append((cursor, gap, "break", bt, bd, "low", "low"))
        cursor = lunch_at
    lt, ld = rng.choice(_LUNCH_VARIANTS)
    plan.append((cursor, 60, "meal", lt, ld, "low", "high"))
    cursor += 60

    # 4. Afternoon blocks — stop when we'd exceed the user's available hours
    end_limit = (start_h * 60 + start_m) + int(round(available_hours * 60))
    aft_block = block_min if zone == "peak" else max(30, block_min - 15)
    afternoon_done = 0
    AFTERNOON_MAX = 5
    while afternoon_done < AFTERNOON_MAX and cursor + aft_block <= end_limit:
        # Honour the soft target: stop if we've met it AND the remaining day is short
        if afternoon_done >= afternoon_blocks_target and (end_limit - cursor) < (aft_block + short_brk + 30):
            break
        if afternoon_done == 0 and zone != "peak":
            et, ed = rng.choice(_EXERCISE_VARIANTS)
            plan.append((cursor, 20, "exercise", et, ed, "low", "medium"))
            cursor += 20
        title, desc = work_pool[work_idx % len(work_pool)]
        work_idx += 1
        priority = "medium" if zone != "low" else "low"
        energy_req = "medium" if zone != "low" else "low"
        plan.append((cursor, aft_block, "work", title, desc, energy_req, priority))
        cursor += aft_block
        afternoon_done += 1
        if afternoon_done < afternoon_blocks_target:
            bt, bd = rng.choice(_BREAK_VARIANTS)
            plan.append((cursor, short_brk, "break", bt, bd, "low", "low"))
            cursor += short_brk

    # 5. Wind down
    rt, rd = rng.choice(_REST_VARIANTS)
    plan.append((cursor, 30, "rest", rt, rd, "low", "low"))
    cursor += 30

    # --- Trim to available_hours if needed
    end_limit_min = (start_h * 60 + start_m) + int(round(available_hours * 60))
    plan = [p for p in plan if p[0] < end_limit_min]
    if not plan:  # safety
        plan = [(start_h * 60 + start_m, 60, "rest", "Rest day",
                 "Available hours too low — recover today.", "low", "high")]

    # --- Personalised recommendations
    recs = _build_recommendations(zone, profile, block_min, short_brk, n_blocks)

    # --- Serialise
    tasks: List[ScheduleTask] = []
    work_min_total = 0
    break_min_total = 0
    for i, (start_min, dur, ttype, title, desc, energy_req, priority) in enumerate(plan, start=1):
        h, m = divmod(start_min, 60)
        time_str = f"{h:02d}:{m:02d}"
        tasks.append(ScheduleTask(
            id=i,
            time=time_str,
            duration=dur,
            taskType=ttype,
            title=title,
            description=desc,
            personalizationReason=_build_task_personalization_reason(
                task_type=ttype,
                title=title,
                start_min=start_min,
                duration=dur,
                zone=zone,
                predicted_energy=predicted_energy,
                available_hours=available_hours,
                profile=profile,
                block_min=block_min,
                short_brk=short_brk,
                lunch_start=LUNCH_START,
            ),
            energyRequired=energy_req,
            priority=priority,
        ))
        if ttype == "work":
            work_min_total += dur
        elif ttype == "break":
            break_min_total += dur

    return zone, tasks, recs, work_min_total, break_min_total


def _build_recommendations(
    zone: str,
    profile: UserProfile,
    block_min: int,
    short_brk: int,
    n_blocks: int,
) -> List[str]:
    """Build human-readable, personalised tips."""
    recs: List[str] = []

    if zone == "peak":
        recs.append("Energy is high — protect your morning for deep work.")
    elif zone == "moderate":
        recs.append("Energy is moderate — pace yourself with regular breaks.")
    else:
        recs.append("Energy is low today — be gentle with yourself.")

    # Personalised line based on the user's averages
    recs.append(
        f"Tuned for you: {block_min}-min focus blocks, "
        f"{short_brk}-min breaks, {n_blocks} work blocks today "
        f"(based on your typical {profile.avg_sleep_hours:.1f} h sleep, "
        f"focus level {profile.avg_focus_level:.1f}/10, "
        f"~{profile.avg_tasks:.0f} tasks/day)."
    )

    if profile.avg_sleep_hours < 6.5:
        recs.append("You've been sleeping under 6.5 h on average — prioritise an earlier bedtime tonight.")
    elif profile.avg_sleep_hours > 8.5:
        recs.append("You sleep generously (>8.5 h average) — schedule later morning starts to fit your rhythm.")

    if profile.avg_focus_level < 5:
        recs.append("Your focus has trended low — try removing one source of distraction (notifications, browser tabs).")
    elif profile.avg_focus_level >= 8:
        recs.append("Your focus is consistently strong — consider extending one block to a 2-hour deep dive.")

    if profile.avg_break_min < 20:
        recs.append("You take very few breaks — even a 5-min walk every 90 min boosts afternoon energy.")
    elif profile.avg_break_min > 90:
        recs.append("Breaks are generous — make sure each one is restorative, not just scrolling.")

    return recs
