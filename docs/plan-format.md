# Workout plan file format

The Training Log app (Lift → Program → Import a plan from Claude) reads workout plans as JSON.
Give this prompt to Claude (or any AI) before asking for a plan; paste its whole reply into the app.

## Prompt

````text
I use a workout tracker app that imports workout plans as JSON. When I ask you for a workout plan, reply with ONE JSON code block in exactly this format (plus any explanation you like outside the code block). I'll paste your whole reply into the app.

{
  "format": "training-log-plan",
  "version": 1,
  "name": "Short plan name",
  "schedule": "weekdays",
  "workouts": [
    {
      "name": "Push",
      "note": "optional short description",
      "split": "push",
      "days": ["Mon", "Thu"],
      "exercises": [
        { "name": "Bench Press", "main": true, "sets": 3, "reps": 5, "weight": 135,
          "progression": { "type": "linear", "increment": 5 } },
        { "name": "Lateral Raise", "sets": 3, "repRange": [12, 20], "weight": 15,
          "progression": { "type": "double", "increment": 5 } },
        { "name": "Push-Up", "bodyweight": true, "sets": 2, "reps": 12,
          "progression": { "type": "reps" } }
      ]
    }
  ]
}

RULES
- schedule: "weekdays" = each workout repeats on its "days" (use "Sun","Mon","Tue","Wed","Thu","Fri","Sat"). "rotation" = workouts are done in list order whenever I train; "days" are then just suggestions.
- split (optional): one of "upper","lower","push","pull","legs","full" — colors the workout on the app's calendar.
- Each exercise needs "name" and "sets" (1-12), plus EITHER "reps" (a number) OR "repRange" ([low, high]).
- weight: starting weight in lb (number), or null if unknown — the app fills it from my history or asks on the first set. For bodyweight exercises set "bodyweight": true; for those, "weight" means ADDED weight (0 or omit).
- main: true for the 1-3 big lifts of the day (shows warm-up sets and a longer rest timer).
- rest (optional): rest between sets in seconds. Defaults: main 180, others 90.
- note (optional): short cue shown under the exercise, e.g. "3 seconds down".
- progression.type must be one of:
  - "linear": fixed reps; when every set hits the reps, add "increment" lb next time. Optional: "firstIncrement" (bigger jumps until the first miss), "missesBeforeDeload" (default 2), "deloadPercent" (default 10).
  - "double": needs repRange; when every set reaches the top of the range, add "increment" lb and restart at the bottom.
  - "reps": bodyweight builder; adds one rep to the weakest set each session all sets are hit. Optional: "weightedAfterTotalReps" (e.g. 30) switches to "weightedSets" x "weightedReps" with "increment" lb added.
  - "none": just a checklist item, no automatic changes.
- Use common exercise names (e.g. "Squat", "Romanian Deadlift", "Lat Pulldown", "Dumbbell Curl"). Keep every exercise rep-based (no timed holds).
- Only use the fields shown above. Output valid JSON: double quotes, no comments, no trailing commas.

Before writing the plan, ask me anything you need: goals, how many days a week I can train, equipment, injuries, and what weights I currently use.
````
