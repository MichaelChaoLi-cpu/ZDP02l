# Response to reviewers and editors of manuscript number [MANUSCRIPT ID]

Note: All quoted manuscript text must match the fresh clean version exactly.
All line and page numbers refer to that same version and require human
verification when they cannot be derived reliably.
Factual explanations prefer the simple present, and each response keeps a
consistent local tense unless chronology requires otherwise. Exact manuscript
quotations remain verbatim.

# Revision Summary

Thanks for the editor and reviewers’ careful review. We hereby resubmit a substantially revised version of our manuscript that addresses all points raised by the editor and reviewers.

The main changes in the revised manuscript are:

- [Revision summary item 1: describe the major manuscript-level change.]
- [Revision summary item 2: describe the major theoretical or conceptual change.]
- [Revision summary item 3: describe the major methodological or robustness-check change.]
- [Revision summary item 4: describe the major results, discussion, table, or figure change.]
- [Revision summary item 5: describe language polishing, consistency checks, or formatting changes.]

The revised manuscript also addresses the editor’s and reviewers’ other comments, and detailed responses to each reviewer follow.

Finally, we would like to express our sincere gratitude to the editor and reviewers. We hope that these changes meet your expectations, and we look forward to receiving your decision on the improved version of our manuscript.

# Editor

Dear Dr Managi,

Your manuscript, "The Rural Happiness Paradox: Economic Insecurity and Social Support as Mediators of Global Rural-Urban Well-being Disparities", has now been assessed.

We invite you to revise your paper, carefully addressing the comments from the reviewers and the editor. Please ensure the results are accurately reported, any overstated conclusions are rewritten and the limitations of the work fully explained. When your revision is ready, please submit the updated manuscript and a point-by-point response. This will help us move to a swift decision.

Editor Comments

"Dear Authors,

Both reviewers acknowledged the manuscript's value and relevance but identified several valid points that warrant a major revision. For example, the current analytical strategy does not adequately support the manuscript's claims regarding mediation. The authors need to justify their modeling choices more clearly and, if necessary, consider using alternative modeling strategies. The theoretical discussion should also be revised and given greater emphasis.

The reviewers recommend performing robustness checks, including alternative models if necessary for the outcome variable. Please also make sure that the paper avoid overstating its global coverage and causal conclusions, shorten overly detailed sections and remove redundant tables and figures. Finally, policy recommendations should remain cautious and closely tied to the empirical evidence. Based on the reviewers' feedback, I recommend a major revision."

**Response:**
[Response pending.]

> [Exact revised text quoted from the fresh clean manuscript]

(Lines/Pages: human verification required)

# Reviewer 1

## Overall Comment


Overall, this study is very interesting and clearly written. The author(s) provided a cross-region analysis of the rural-urban differences in subjective well-being and made valuable contributions to the literature. Please find below some comments/suggestions.

**Response:**
[Response pending.]

> [Exact revised text quoted from the fresh clean manuscript]

(Lines/Pages: human verification required)

## Comment 1

1. I have some doubts about the modeling strategies.
a. The author(s) used a sequential decomposition strategy to examine the mechanisms for the rural-urban differences, but I don’t think the strategy is appropriate in this case. Instead, it is more like adding confounding factors. Therefore, a more formal strategy (e.g., mediation analysis) is perhaps better suited for the mechanism analysis.

**Response:**
[Response pending.]

> [Exact revised text quoted from the fresh clean manuscript]

(Lines/Pages: human verification required)

## Comment 2

b. Currently, the sequential regression models (with country level fixed effects) and the cross-country heterogeneity analysis are conducted separately for different purposes of the study, but a multi-level model with fixed effects specifications might be better (and by the way, it also allows for incorporating some country/region-level factors), which can even lend power to countries with few observations (below 100 in the data). So the author(s) may need to provide some reasoning for why not using multi-level models.

**Response:**
Thank you for this important suggestion. We agree that the nested data structure and cross-place heterogeneity require explicit treatment. The revised *Analytical Approach* now places fixed effects in every primary OLS model, uses place-clustered CR2 standard errors with Satterthwaite corrections, and adds a Webb six-point wild-cluster score-bootstrap check for the focal rural-residence coefficient. We retain place-fixed-effects OLS as the primary specification because the estimand is the within-place rural–urban association and the included places are not treated as a random sample from a broader population. We also add a correlated random-intercept and rural-random-slope Gaussian multilevel model on the same common sample as a robustness and heterogeneity analysis.

> All primary models include place fixed effects and use place-clustered CR2 standard errors with Satterthwaite degrees-of-freedom corrections (Fanfan et al., 2025; Hu et al., 2025; Lu et al., 2025) to account for within-place dependence (da Silva et al., 2024; Wei et al., 2024; Zhao et al., 2022) and the small number of place clusters (da Silva et al., 2024; Lu et al., 2025; Tsurumi et al., 2021). For the focal rural-residence coefficient, we additionally report a Webb six-point wild-cluster score-bootstrap check (Casini et al., 2021; Wei et al., 2024; Yu et al., 2022). Place fixed effects remain the primary specification because the estimand is the within-place rural-urban association and the included places are not treated as a random sample from a broader population (da Silva et al., 2024; Lu et al., 2025; Tsurumi et al., 2021). As a robustness and heterogeneity analysis, we estimate a Gaussian linear mixed model with correlated place random intercepts and rural random slopes on the same common sample and with the same full individual-level covariates as the primary final model, thereby partially pooling place-specific rural associations (da Silva et al., 2024; Wei et al., 2024; Zhao et al., 2022).

The common-sample audit also shows that all 23 places include both rural and urban respondents and that the smallest place contains 1,310 complete observations; thus, no place is excluded by a small-sample threshold. The revised *Country-Level Heterogeneity* section states:

> The multilevel robustness model complements them by partially pooling place-specific rural associations through correlated place random intercepts and rural random slopes. In the common sample, all 23 places include both rural and urban respondents and contain at least 1,310 complete observations, so no place is excluded by a small-sample threshold.

The multilevel fixed rural association is 0.068 points (95% small-cluster *t* interval: 0.013 to 0.124), close to the fully adjusted place-fixed-effects OLS estimate. The random-slope standard deviation is 0.111, and the partially pooled place-specific slopes range from −0.095 to 0.348. We therefore present the multilevel model as complementary evidence of heterogeneity rather than as a replacement for the primary OLS specification:

> In the multilevel robustness model with correlated place random intercepts and rural random slopes, the fixed rural association is 0.068 points on the 0-10 life-satisfaction scale (95% small-cluster t interval: 0.013 to 0.124), close to the fully adjusted place-fixed-effects OLS estimate. The rural random-slope standard deviation is 0.111, and the partially pooled place-specific rural slopes range from -0.095 to 0.348. These results indicate heterogeneity in both the magnitude and direction of the rural association across places, while the positive fixed association is broadly directionally consistent with the primary OLS result. The multilevel estimates therefore complement rather than replace the within-place fixed-effects specification.

Finally, the revised *Limitations and Future Studies* section makes clear that partial pooling does not identify the contextual sources of heterogeneity:

> A further limitation is that, although the multilevel robustness model partially pools place-specific rural associations, the analysis includes only 23 places and lacks harmonized place-level covariates; it therefore cannot identify which contextual factors generate the observed heterogeneity.

(Lines 322–336, 440–444, 569–577, and 858–861; Pages 15–16, 21, 26–27, and 39.)

## Comment 3

b. The steps in the “Sequential Model Specifications for Life Satisfaction” appear too cumbersome and can be downsized with updated framing. For instance, it might be better to include country level fixed effects in all models rather than only adding them in M4 and later models.

**Response:**
[Response pending.]

> [Exact revised text quoted from the fresh clean manuscript]

(Lines/Pages: human verification required)

## Comment 4

c. The authors conducted an independent “Economic Insecurity Analysis”, where three measures were used as dependent variables. If this strategy is reasonable, which I highly doubt, why don’t fit a similar model for the social capital index (which is listed as a separate mechanism by the authors)? In addition, why don’t integrate this independent analysis into the “Mechanism Analysis” subsection?

**Response:**
[Response pending.]

> [Exact revised text quoted from the fresh clean manuscript]

(Lines/Pages: human verification required)

## Comment 5

2. There are some issues with the “Data and Measurement” and “Methodology” sections.
a. Overall, there are a lot of details, such as the description of data preprocessing, that could be deleted to keep the manuscript concise. It might be better to include some of them (together with the corresponding figures/tables) in the appendix or supplementary materials.

**Response:**
[Response pending.]

> [Exact revised text quoted from the fresh clean manuscript]

(Lines/Pages: human verification required)

## Comment 6

b. There are some organizational issue as well: some of the focal independent and mediator variables are messed with control variables at one place or another. For instance, “Income Security Feelings” (added in M3) serves as a socioeconomic control, not as a measure of economic insecurity (added in M5): in “Data and Measurement” section, it is somehow grouped under the category “Economic Insecurity Measures”. And the measure description, descriptive results and methodology were also mixed together in ways that are quite unexpected.

**Response:**
[Response pending.]

> [Exact revised text quoted from the fresh clean manuscript]

(Lines/Pages: human verification required)

## Comment 7

c. If I am not mistaken, the sample sizes are somehow inconsistent across models/tables (?). Is it due to missing values in the data? Anyway, this may make the comparison of results across models/tables questionable.

**Response:**
[Response pending.]

> [Exact revised text quoted from the fresh clean manuscript]

(Lines/Pages: human verification required)

## Comment 8

3. Some other minor issues:
a. The authors may consider adding a table/figure of the unadjusted differences between rural and urban residents across countries/regions.

**Response:**
[Response pending.]

> [Exact revised text quoted from the fresh clean manuscript]

(Lines/Pages: human verification required)

## Comment 9

b. Please be extremely careful about the term “country” in the manuscript. Hongkong is not a country, and it’s thus better to use other terms such as region (by the way, the inclusion of Hong Kong in the comparison also looks weird as it is quite different from other places).

**Response:**
[Response pending.]

> [Exact revised text quoted from the fresh clean manuscript]

(Lines/Pages: human verification required)

## Comment 10

c. Regarding the “Within-Country Income Percentile” measure, I am not sure how it was collected in the survey. Moreover, according to the “relative income comparisons” reasoning in the “Introduction” section, it might be better to use the percentiles within the rural and urban population separately.

**Response:**
[Response pending.]

> [Exact revised text quoted from the fresh clean manuscript]

(Lines/Pages: human verification required)

## Comment 11

d. Tables and figures appear somewhat redundant in certain places, such as Figure 4 and Table 2. Please review them carefully and consider excluding some tables/figures from the manuscript, including but not limited to Figures 1, 2, and 5.

**Response:**
[Response pending.]

> [Exact revised text quoted from the fresh clean manuscript]

(Lines/Pages: human verification required)

## Comment 12

e. Not sure about the category “Unknown-25” in Figure 3.

**Response:**
Thank you for noting this labeling issue. We verified that source country code 25 corresponds to China, corrected the shared place-name crosswalk, and regenerated Figure 3. The revised figure now displays `China` and no longer contains the `Unknown-25` label.

The revised figure reads:

> China
>
> Figure 3. Share of rural residence by country

(Page/line: Page 51, Figure 3; caption at line 943)

## Comment 13

f. The reference line crossed the subtitle in Figure 5.

**Response:**
[Response pending.]

> [Exact revised text quoted from the fresh clean manuscript]

(Lines/Pages: human verification required)

## Comment 14

g. Are there any differences between Figures 4 and 6?

**Response:**
[Response pending.]

> [Exact revised text quoted from the fresh clean manuscript]

(Lines/Pages: human verification required)

## Comment 15

h. Some claims in the manuscript appear somewhat overstated, such as “global evidence” and “adjusting for country-specific factors”, and the author(s) may consider changing the wording a little bit.

**Response:**
[Response pending.]

> [Exact revised text quoted from the fresh clean manuscript]

(Lines/Pages: human verification required)

## Comment 16

i. The “Policy Implications” subsection is too long and, in some places, appears to make claims that extend beyond the evidence directly supported by the study. The author(s) may consider shortening it and framing the implications more cautiously.

**Response:**
[Response pending.]

> [Exact revised text quoted from the fresh clean manuscript]

(Lines/Pages: human verification required)

## Comment 17

j. The “Limitations and Future Studies” subsection is also too long.

**Response:**
[Response pending.]

> [Exact revised text quoted from the fresh clean manuscript]

(Lines/Pages: human verification required)

# Reviewer 2

## Overall Comment

Summary of the manuscript:
The paper studies the so-called “rural happiness paradox” – the empirical finding that people living in rural areas sometimes report similar or even higher life satisfaction than people living in cities, even though they face clear economic disadvantages. The topic is highly relevant, the dataset is large and international, and the research questions are clearly defined. However, the manuscript contains several important methodological, interpretative, and presentation issues that need to be addressed before it can be considered for publication.

Overall assessment 
The article addresses an important and globally relevant question using a large international dataset. However, there are inconsistencies between the reported results and their interpretation. The paper also makes claims about mediation that are not methodologically supported, and the overall framing tends to confuse rather than clarify the main findings.

Major comments

**Response:**
[Response pending.]

> [Exact revised text quoted from the fresh clean manuscript]

(Lines/Pages: human verification required)

## Comment 1

1. Interpretation of mediation
In both the Results and Discussion sections, the authors repeatedly state that adding economic insecurity variables in Model M5 reduces the rural coefficient compared to Model M4. However, Table 4 shows that the rural coefficient actually increases. 
The same increase is also visible in Figure 6. The coefficient only returns to +0.060 in Model M6 after adding the Social Capital Index.
The authors write: “its size decreased after including income security feelings, expense worries, and income percentile in M5”. However, both the table and figure clearly show an increase. This is likely not a typo but a serious interpretation error, because the entire discussion about economic insecurity as a main mediating mechanism is based on this incorrect direction of change.

**Response:**
[Response pending.]

> [Exact revised text quoted from the fresh clean manuscript]

(Lines/Pages: human verification required)

## Comment 2

2. Key sign reversal is driven by a variable used twice in different roles
The paper argues that the rural disadvantage (β = −0.109 in M1) becomes a rural advantage (β = +0.060 in M6) due to economic insecurity and social capital mechanisms. However, this argument is weakened by inconsistent use of variables. The sign change already happens in Model M3 (β = +0.040), not in M5. In Model M3, Income Security Feelings is included as a control variable (Table 2). Later, the same variable is treated as part of the economic insecurity mechanism (Table 3). Thus, the variable plays two roles: (i) As a control, it contributes to the sign reversal in M3, and (ii) as a mechanism variable, it is later used to explain changes in M4–M5 
This mixing of roles hides where the real explanatory power comes from.

**Response:**
[Response pending.]

> [Exact revised text quoted from the fresh clean manuscript]

(Lines/Pages: human verification required)

## Comment 3

3. Sequential OLS models are not evidence of mediation
The term “mediation” is used throughout the manuscript, including section titles and discussion. However, the authors only use sequential regression models.
They should conduct a proper mediation analysis using SEM or path analysis, where direct and indirect effects are estimated and tested. Only then can the authors make claims about partial or full mediation. Without this, the current interpretation is not methodologically valid.

**Response:**
[Response pending.]

> [Exact revised text quoted from the fresh clean manuscript]

(Lines/Pages: human verification required)

## Comment 4

4. Social capital data contradicts the theoretical narrative
The Discussion repeatedly claims that rural residents have stronger social ties, higher community cohesion, and more social support. However, Table 1 shows the opposite.
The claim that rural areas have higher social capital is therefore not supported by the data. The Discussion must be revised to match the actual results.
In particular, the idea that social capital works as a “buffer” or “compensatory” mechanism for rural areas needs to be reconsidered.

**Response:**
[Response pending.]

> [Exact revised text quoted from the fresh clean manuscript]

(Lines/Pages: human verification required)

## Comment 5

5. Missing country-level mediation analysis
The study shows strong differences between countries (Figure 7), but does not test whether economic insecurity and social capital work as mediators in all countries in the same way.
This is an important limitation. The mediation mechanisms may differ depending on national context.

**Response:**
[Response pending.]

> [Exact revised text quoted from the fresh clean manuscript]

(Lines/Pages: human verification required)

## Comment 6

6. No grouping of countries by geography or culture
The forest plot only lists countries ordered by effect size. It does not show whether similar countries behave in similar ways. It would be useful to group countries by shared characteristics (history, culture). This could reveal meaningful patterns in the results.

**Response:**
[Response pending.]

> [Exact revised text quoted from the fresh clean manuscript]

(Lines/Pages: human verification required)

## Comment 7

7. Claim of “global” coverage is overstated
The sample includes 22 countries from the GFS dataset, which cannot be considered globally representative. For example, countries such as India (with the world’s largest rural population) are missing. The authors should avoid using the term “global” too strongly.

Minor comments

**Response:**
[Response pending.]

> [Exact revised text quoted from the fresh clean manuscript]

(Lines/Pages: human verification required)

## Comment 8

8. “Unknown_25” label in Figure 3
The country labelled “Unknown_25” must be identified and corrected.

**Response:**
Thank you for identifying this issue. We verified that source country code 25 corresponds to China, corrected the shared place-name crosswalk, and regenerated Figure 3. The revised figure now displays `China` and no longer contains the `Unknown_25` label.

The revised figure reads:

> China
>
> Figure 3. Share of rural residence by country

(Page/line: Page 51, Figure 3; caption at line 943)

## Comment 9

9. OLS for a bounded outcome
The authors should include at least an ordered logit model as a robustness check.

**Response:**
[Response pending.]

> [Exact revised text quoted from the fresh clean manuscript]

(Lines/Pages: human verification required)

## Comment 10

10. Z-score construction of social capital
It must be clarified whether z-scores were calculated within each country or across the full sample.

**Response:**
[Response pending.]

> [Exact revised text quoted from the fresh clean manuscript]

(Lines/Pages: human verification required)

## Comment 11

11. Contextualizing country differences
The discussion should compare countries where rural areas show advantages (e.g., Poland, Tanzania, Kenya) with those where they show disadvantages (e.g., Israel, Japan).

**Response:**
[Response pending.]

> [Exact revised text quoted from the fresh clean manuscript]

(Lines/Pages: human verification required)

## Comment 12

12. Policy implications are too general
Policy recommendations should be more directly based on the study’s findings rather than general statements.

**Response:**
[Response pending.]

> [Exact revised text quoted from the fresh clean manuscript]

(Lines/Pages: human verification required)
