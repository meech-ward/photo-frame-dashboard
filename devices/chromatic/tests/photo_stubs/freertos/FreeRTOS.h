#pragma once
typedef int portMUX_TYPE;
#define portMUX_INITIALIZER_UNLOCKED 0
#define portENTER_CRITICAL(mutex) ((void)(mutex))
#define portEXIT_CRITICAL(mutex) ((void)(mutex))
