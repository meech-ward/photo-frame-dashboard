#pragma once
#define ESP_RETURN_ON_FALSE(condition, value, tag, ...) do { (void)(tag); if (!(condition)) return (value); } while (0)
#define ESP_GOTO_ON_FALSE(condition, value, label, tag, ...) do { (void)(tag); if (!(condition)) { ret = (value); goto label; } } while (0)
