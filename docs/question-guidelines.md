# Question guidelines: The Lifelong Quiz

The rules every bundled pack in `quiz/packs/` follows (applied 2026-10-25 to all 7,500 questions).

The Lifelong Quiz is a live YouTube quiz show. Viewers from every country answer in chat:
- in the evening across Europe and the Americas;
- in India and South-East Asia (13:00 UTC);
- in East Asia and Oceania.

All text is in English. Every question must be fair to a well-informed viewer **anywhere in the world**.

## 1. The global rule (the most important one)

**Keep a question only if a curious, well-read person who has never lived in a given country
could reasonably know the answer.**

Not allowed: questions only residents or citizens of one country would know. For example:
- US (or any country's) domestic politics: senators, governors, state laws, election slogans,
  campaign trivia, a leader's children, party internals, national cabinet posts;
- US states and state capitals, area codes, zip codes, local chains and brands;
- national school curricula, local TV shows that never aired abroad, regional sports leagues
  and their minor players (NFL depth, college sports, cricket county teams, etc.);
- national holidays' local details, local currencies' slang, local measurement habits.

Allowed: things of world fame, even when they belong to one country:
- the Eiffel Tower, the Taj Mahal;
- Abraham Lincoln, Gandhi, Mandela, Napoleon;
- the Olympics, the FIFA World Cup, the Tour de France, Wimbledon;
- Hollywood, Bollywood and K-pop hits known worldwide;
- famous global brands, world capitals, the UN, the EU.

Politics is allowed as **world** politics and civics:
- international organisations and treaties;
- political systems and terms;
- historic world leaders and events of global fame;
- flags, capitals and independence years.

**Spread the world.** Questions that need a region must rotate across:
- Asia (India, China, Japan, Korea, South-East Asia);
- Africa;
- the Middle East;
- Europe;
- Latin America;
- North America;
- Oceania.

No one region may be more than about 25% of the region-tied questions in a file.

**Keep it timeless.** Don't ask facts that change, such as current office holders, current
champions or "the latest" anything, unless the question names the year ("Who won the 2014
FIFA World Cup?").

**Units.** Use metric units. You may add imperial in brackets. Never use Fahrenheit-only or
US-only units, and never write dates that read differently by country.

**Not easy, just fair.** Keep hard and expert questions hard. Niche topics are fine, such as
anime, board games or opera. The rule is that the niche must be a worldwide one, not one
country's.

## 2. Format: regular questions (JSON list)

```json
{"question": "Which river flows through Baghdad?", "correct": "Tigris",
 "incorrect": ["Euphrates", "Jordan", "Nile"], "category": "Geography",
 "difficulty": "medium", "fact": "Baghdad was founded on the Tigris in 762 CE."}
```

- `question`: at most 110 characters. Aim for 40-80. It must be one clear question with exactly
  one right answer. Never write "Which of these..." with an option that could also be right.
- `correct`, plus exactly **3** `incorrect`: each at most 28 characters.
  - All four must be the same kind of thing and be plausible.
  - Do not repeat options.
  - Do not use "All of the above" or "None of these".
- `category`: use EXACTLY the category name you were given, for example
  `"Entertainment: Board Games"`.
- `difficulty`: one of `easy`, `medium`, `hard`, `expert`.
  - Aim for roughly 25% easy, 35% medium, 30% hard and 10% expert.
  - `expert` is for the match final: something a real fan or specialist knows.
- `fact`: one surprising, true sentence of at most 120 characters, shown after the answer.
  Don't repeat the answer as the whole fact.
- **Be correct.** Only write a fact you are sure of. If you are unsure, skip it and write a
  different question. A wrong answer on live TV is worse than one question fewer.
- **No duplicates.** Check the existing questions you are given, and don't ask the same thing
  in different words.
- **Safe for all ages.** No gore, no sexual content, no slurs, no living-person gossip, and no
  questions that mock a nation, religion or group.

## 3. Formats: special rounds (JSON list, same file rules)

**Higher or lower:** two options, `answer` is the index of the right one.

```json
{"type": "higher_lower", "question": "Higher or lower: is the Nile longer than 6,000 km?",
 "options": ["Longer", "Shorter"], "answer": 0, "category": "Geography", "difficulty": "medium",
 "fact": "The Nile is about 6,650 km long."}
```

The option words must match the question, for example Taller/Shorter, More/Fewer,
Older/Younger, Heavier/Lighter, Higher/Lower or Longer/Shorter. The number in the question
must not be within 3% of the true value.

**Crowd Mind:** an opinion question, so there is no right answer and no `answer` field. It has
4 options of at most 22 characters each. It must be fun for every culture: food, superpowers,
travel, animals, "would you rather" and so on.

```json
{"type": "majority", "question": "Crowd Mind: which breakfast would most of chat pick?",
 "options": ["Pancakes", "Rice and eggs", "Fruit bowl", "Toast"], "category": "General Knowledge",
 "difficulty": "easy", "fact": ""}
```

**Odd one out:** 4 options, `answer` is the index of the one that does not belong, and the
`fact` says why. Exactly one option may fit as the odd one.

```json
{"type": "odd_one_out", "question": "Odd one out: which is not a capital city?",
 "options": ["Canberra", "Ottawa", "Sydney", "Wellington"], "answer": 2,
 "category": "Geography", "difficulty": "easy", "fact": "Sydney is Australia's biggest city; Canberra is the capital."}
```

## 4. Output

- Write valid JSON, UTF-8, as one list per file.
- Write in batches of about 50 questions per file, so a crash loses little.
- Validate each file after writing it:
  `python -c "import json,sys; d=json.load(open(sys.argv[1],encoding='utf-8')); print(len(d))" FILE`
