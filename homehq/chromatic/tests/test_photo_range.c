/* Pure protocol checks; every header and tag is synthetic. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include "../src/homehq_photo_range.h"

static bool parse(const char *value, size_t start, size_t end, size_t fixed, size_t want, size_t count)
{
    size_t total = SIZE_MAX, length = SIZE_MAX;
    bool accepted = HQ_PhotoRangeParse(value, start, end, fixed, &total, &length);
    if (accepted) assert(total == want && length == count && length <= 4096);
    else assert(!total && !length);
    return accepted;
}
int main(void)
{
    char header[96]; size_t fixed = 0, offset = 0;
    for (unsigned range = 0; range < 80; ++range) {
        size_t end = offset + 4095;
        snprintf(header, sizeof(header), "bytes %zu-%zu/327680", offset, end);
        assert(parse(header, offset, end, fixed, 327680, 4096));
        fixed = 327680; offset += 4096;
    }
    assert(offset == 327680);
    assert(parse("bytes 0-31/32", 0, 4095, 0, 32, 32));
    assert(parse("bytes 4096-4999/5000", 4096, 8191, 5000, 5000, 904));
    assert(parse("bytes 327679-327679/327680", 327679, 331774, 327680, 327680, 1));
    assert(parse("bytes 0000-04095/0327680", 0, 4095, 0, 327680, 4096));
    const char *invalid[] = {
        "", "bytes", "bytes ", "Bytes 0-4095/327680", " bytes 0-4095/327680",
        "bytes 0-4095/327680 ", "bytes 0-4095/327680\r\n", "bytes  0-4095/327680",
        "bytes +0-4095/327680", "bytes -0-4095/327680", "bytes 0--4095/327680",
        "bytes 0-4095/+327680", "bytes 0-4095/-327680", "bytes 0-4095/*",
        "bytes */327680", "bytes 0:4095/327680", "bytes 0-4095:327680",
        "bytes 0 -4095/327680", "bytes 0- 4095/327680", "bytes 0-4095 /327680",
        "bytes 0-4095/ 327680", "bytes 0-4095/0", "bytes 0-4095/4095",
        "bytes 0-4095/327681", "bytes 0-327681/327680", "bytes 327681-327681/327680",
        "bytes 0-4094/327680", "bytes 0-4096/327680", "bytes 1-4095/327680",
        "bytes 4095-0/327680", "bytes 0-999999999999999999999999999999999999999999999999/327680",
        "bytes 0-4095/999999999999999999999999999999999999999999999999", "bytes 0-4095/327680, bytes 0-4095/327680"
    };
    for (size_t i = 0; i < sizeof(invalid) / sizeof(invalid[0]); ++i)
        assert(!parse(invalid[i], 0, 4095, 0, 0, 0));
    assert(!parse(NULL, 0, 4095, 0, 0, 0));
    assert(!parse("bytes 0-4095/327680", 0, 4095, 327679, 0, 0));
    assert(!parse("bytes 0-4095/327680", 0, 4095, 327681, 0, 0));
    assert(!parse("bytes 0-8191/327680", 0, 8191, 0, 0, 0));
    assert(!parse("bytes 0-4095/327680", 1, 0, 0, 0, 0));
    assert(!parse("bytes 0-4095/327680", SIZE_MAX, SIZE_MAX, 0, 0, 0));
    assert(!parse("bytes 0-4095/327680", 0, SIZE_MAX, 0, 0, 0));
    size_t result;
    assert(!HQ_PhotoRangeParse("bytes 0-4095/327680", 0, 4095, 0, NULL, &result));
    assert(!HQ_PhotoRangeParse("bytes 0-4095/327680", 0, 4095, 0, &result, NULL));
    assert(!HQ_PhotoRangeParse("bytes 0-4095/327680", 0, 4095, 0, &result, &result));
    const char *tags[] = {"\"\"", "\"synthetic-etag\"", "\"a/b\\c!#-1\""};
    for (size_t i = 0; i < sizeof(tags) / sizeof(tags[0]); ++i) assert(HQ_PhotoETagValid(tags[i]));
    const char *bad_tags[] = {"", "tag", "W/\"tag\"", "w/\"tag\"", " \"tag\"", "\"tag\" ",
                              "\"with space\"", "\"inner\"quote\"", "\"line\r\n\"", "\"tab\t\"", "\"\177\"", "\"\200\""};
    assert(!HQ_PhotoETagValid(NULL));
    for (size_t i = 0; i < sizeof(bad_tags) / sizeof(bad_tags[0]); ++i) assert(!HQ_PhotoETagValid(bad_tags[i]));
    char tag[98]; memset(tag, 'x', sizeof(tag)); tag[0] = '"'; tag[95] = '"'; tag[96] = 0;
    assert(HQ_PhotoETagValid(tag)); tag[95] = 'x'; tag[96] = '"'; tag[97] = 0;
    assert(!HQ_PhotoETagValid(tag));
    puts("photo ranges: 80 chunks, exact endpoints, fixed totals, overflow, malformed fields and strong bounded ETags passed");
    return 0;
}
