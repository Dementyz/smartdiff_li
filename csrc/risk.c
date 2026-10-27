#include "sd_core.h"

#define SD_SCORE_ADDED 0.5
#define SD_SCORE_REMOVED 6.0
#define SD_SCORE_BODY 3.0
#define SD_SCORE_DOC 0.0
#define SD_SCORE_MOVED 1.0
#define SD_SCORE_BREAKING_SIGNATURE 8.0
#define SD_SCORE_COMPATIBLE_SIGNATURE 2.0
#define SD_BROKEN_REF_SCORE 15.0
#define SD_MAX_BROKEN_REFS 3
#define SD_PRIVATE_FACTOR 0.5
#define SD_TEST_FACTOR 0.2

static int32_t min32(int32_t a, int32_t b) { return a < b ? a : b; }

double sd_change_score(const sd_change_info *c) {
    double base;
    switch (c->change) {
    case SD_ADDED: base = SD_SCORE_ADDED; break;
    case SD_REMOVED: base = SD_SCORE_REMOVED; break;
    case SD_BODY: base = SD_SCORE_BODY; break;
    case SD_MOVED: base = SD_SCORE_MOVED; break;
    case SD_SIGNATURE:
        base = c->breaking ? SD_SCORE_BREAKING_SIGNATURE : SD_SCORE_COMPATIBLE_SIGNATURE;
        break;
    default: base = SD_SCORE_DOC; break;
    }
    double public_factor = c->is_public ? 1.0 : SD_PRIVATE_FACTOR;
    double fan_in = 1 + 0.3 * min32(c->direct, 10) + 0.05 * min32(c->total - c->direct, 20);
    double score = base * public_factor * fan_in
                   + SD_BROKEN_REF_SCORE * min32(c->broken, SD_MAX_BROKEN_REFS);
    if (c->is_test)
        score *= SD_TEST_FACTOR;
    return score;
}

const char *sd_level_for(double score) {
    if (score >= 45) return "critical";
    if (score >= 25) return "high";
    if (score >= 10) return "medium";
    return "low";
}
