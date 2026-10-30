# fosset

so basically you give it data and it gives you charts. json, csv or xml, a file or whatever's on your clipboard, and voila, a window pops up with the charts that actually make sense for it. no prompting, no picking axes, no waiting around.

it came from a pretty simple annoyance: claude spits out sql reports as json all the time (usage, metrics, that kind of stuff) and staring at raw json is not it. now i just pipe it in.

## run it

```
uv run fosset examples/orders.csv
pbpaste | uv run fosset
```

or install it once and use it from anywhere:

```
uv tool install -e .
fosset report.json
```

## in the window

* ← → flips through the charts
* s saves the current one as a png in whatever folder you ran it from
* esc closes it

it follows your mac's light or dark mode, and the colors are colorblind safe.

## how it picks charts

it reads the file, figures out what each column is (numbers, dates, categories, ids) and goes from there. dates plus numbers get line charts, categories get ranked bars, a single row of numbers gets big kpi tiles, and you always get the raw table at the end. the chart it thinks you want most shows up first.

there's also a constraint check that throws out any chart that doesn't fit the data, like a column that isn't there or a bar chart of ids. right now it only checks the built in rules, but it's really there for when the llm starts suggesting charts.

## speed

the whole point is that it's fast. on my m5 a normal report goes from command to chart in about half a second, and a 200k row file takes around 1.7s. the very first launch after installing takes a few seconds while macos warms up webkit, after that it's quick.

to keep it that way there are limits: 25 mb max in, and anything past 200k rows gets cut off.

`--timing` prints how long each step took if you're curious.

## what's next

the llm step. the llm only ever sees the column names, types and a couple of sample values, never the actual rows, and all it does is pick which charts to show and write better titles. answers get cached per column layout, so running the same report again doesn't call the llm at all.

## dev

```
uv sync
uv run pytest
```
