# Dashboard freshness warning

The Summary page now shows a visible warning when its generation-bound FPL source
or dashboard export is more than eight hours old. This uses the existing local
capture-health limit. A fresh export cannot hide an old source. Missing or invalid
dates show an unavailable-freshness notice.

The clock updates every minute and when the window regains focus. Reloading checks
for another immutable public generation; the page never mixes files from different
generations. The same warning appears in the existing prediction-versus-actual
publication status. Forecast dates remain independent, and no model or published
forecast value changes.

This is an age warning for the loaded page, not a claim that a server job failed.
It does not send email or desktop notifications. Older packages without the
optional publication-status receipt retain their existing behavior.

Validation: all 777 dashboard tests pass with two workers; lint has no errors and
the production build passes. Browser verification against the retained September
24 generation shows the notice above Summary. The initial unrestricted parallel
test run timed out in unrelated form tests under concurrent operational work;
the bounded full rerun passed without changing those tests.
