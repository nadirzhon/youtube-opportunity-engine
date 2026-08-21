from yoe.pipeline import run
from yoe.providers.mock import MockYouTubeProvider
from yoe.agents import build_opportunity
report = run(MockYouTubeProvider(1337))
opp = report.opportunities[0]
src = [a.video_id for a in report.breakouts]
pkg = build_opportunity(opp, source_titles=src)
print("topic:", pkg.topic)
print("concepts:", len(pkg.concepts), "| chosen:", pkg.chosen.title_hypotheses[0])
print("originality:", pkg.chosen.originality, "| rank:", pkg.chosen.rank_score)
print("script:", len(pkg.script.sections), "sections,", pkg.script.word_count, "words")
print("quality:", "PASS" if pkg.quality.passed else "FAIL", "| score", pkg.quality.score)
for c in pkg.quality.checks: print("   -", c.name, c.passed, c.score)
