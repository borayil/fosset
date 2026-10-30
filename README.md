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

a few more things it can do:

```
fosset report.json --png charts/              # also save every chart as a png
fosset report.json --png charts/ --headless   # just the pngs, no window
fosset report.json --html report.html         # a page you can open in any browser
```

## use it from claude code

fosset is also a claude code plugin. claude picks the charts, a window pops up for you, and claude gets the numbers plus pngs of the charts back, so it sees what you see. no api key needed since claude is the llm here, and your data never leaves your machine.

```
/plugin install fosset --marketplace borayil/fosset
```

then just work like normal. when a query result, metrics dump, benchmark or cost breakdown shows up, claude charts it. or ask it to, or run `/fosset:visualize path/to/file.json`. comparing options for a decision works too, claude lays them out as rows and charts them.

you need [uv](https://docs.astral.sh/uv/) installed. the very first start downloads fosset's dependencies (about 20s, once), after that it starts instantly. windows and pngs are macos only for now, anywhere else you get the numbers plus an html file you can open in a browser.

## in the window

* ← → flips through the charts
* s saves the current one as a png in whatever folder you ran it from
* esc closes it

it follows your mac's light or dark mode, and the colors are colorblind safe.

## how it picks charts

it reads the file, figures out what each column is (numbers, dates, categories, ids) and goes from there. dates plus numbers get line charts, categories get ranked bars, a single row of numbers gets big kpi tiles, and you always get the raw table at the end. the chart it thinks you want most shows up first.

there's also a constraint check that throws out any chart that doesn't fit the data, like a column that isn't there or a bar chart of ids. everything goes through it, the llm's picks included, so a bad guess just gets dropped instead of breaking the window.

## speed

the whole point is that it's fast. on my m5 a normal report goes from command to chart in about half a second, and a 200k row file takes around 1.7s. the very first launch after installing takes a few seconds while macos warms up webkit, after that it's quick.

to keep it that way there are limits: 25 mb max in, and anything past 200k rows gets cut off.

`--timing` prints how long each step took if you're curious.

## the llm part

totally optional, the rules do a fine job on their own. but if you want smarter picks and better titles, make `~/.config/fosset/config.toml`:

```toml
[llm]
provider = "anthropic"
model = "claude-opus-5-5"
# api_key = "sk-ant-..."   # or just export ANTHROPIC_API_KEY
```

or point it at a local model, anything that speaks the openai chat api works (ollama, lm studio, mlx, llama.cpp):

```toml
[llm]
provider = "local"
url = "http://localhost:11434/v1"
model = "qwen3"
```

the window still opens right away with the rule picks. the llm gets asked in the background and its picks swap in when they land, the footer tells you what's going on. if it fails or you're offline you just keep the rule picks.

it only ever sees the column names, their types and 3 sample values per column, never your actual rows. answers get cached per column layout in `~/.cache/fosset/`, so running the same report again is instant and doesn't cost anything. `--no-llm` skips it for one run.

## dev

```
uv sync
uv run pytest
```
