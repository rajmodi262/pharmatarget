# PharmaTarget — Project Charter

*Written before any code. The headline numbers are committed to as **shapes**;
the blanks are filled by the pipeline, whatever they turn out to be.*

---

## Client

Northwind Pharma, US brand team for a branded direct oral anticoagulant (DOAC).
Modelled on apixaban, with rivaroxaban, dabigatran and edoxaban as the branded
competitive set and warfarin as the legacy comparator.

## Situation

Fixed field force of 60 representatives, roughly $15M/year fully loaded.
Brand share flat for two consecutive years.

## Complication

The force is targeted the way the industry targets by default: rank prescribers
by prescription volume, call the top deciles. That rule is structurally wrong.
A high-volume prescriber already at 90% brand share has no headroom; a
mid-volume prescriber at 5% share is where growth actually lives.

## The three questions

1. **Who?** Which prescribers hold untapped branded opportunity, and how often
   should each be called?
2. **How many?** Is a 60-rep force the right size, and what is the marginal rep
   worth?
3. **Where?** How should the country be divided so workload is balanced,
   territories are contiguous, and travel is minimised?

---

## Headline numbers — committed shapes

> **H1 — back-tested, fully earned.**
> Prescribers the 2022 opportunity model flagged as high-potential grew branded
> 30-day fills **___×** faster in 2023 than volume-matched prescribers the model
> did not flag. Top-decile *opportunity* captured **___×** the growth of
> top-decile *volume*.

> **H2 — arithmetic on observed data, no behavioural assumption.**
> Geography-proportional call allocation reaches **___%** of addressable class
> volume. Opportunity-weighted allocation reaches **___%** on an identical call
> budget.

> **H3 — scenario, explicitly labelled.**
> Under a Hill response curve calibrated on the 2022→2023 promotional panel, the
> marginal rep returns **$___** per $1 at 60 reps and breaks even at **___**
> reps. Sensitivity: break-even ranges **___–___** across the assumption grid.

H1 leads. It is the only validated prediction in the project, and validated
prediction is what separates this from a homework assignment.

---

## Rules of engagement

1. **No un-sourced numbers.** Computed → cite the script. Assumed → state value,
   range and basis in `config/economics.yaml`. No third category exists.
2. **Pre-committed pivots.** If the back-test shows no lift, that is reported as
   a finding and the headline moves to H2, which is pure arithmetic and cannot
   fail. If parallel trends fails, every causal word is deleted. Both decisions
   were made *before* seeing the result.
3. **Answer first.** README sentence one is the recommendation. Deck slide two
   is the recommendation.
4. **Own the limitations.** They are section 6 of the README, not an appendix.

## Success criterion

A partner would send this to a client without rewriting it.
