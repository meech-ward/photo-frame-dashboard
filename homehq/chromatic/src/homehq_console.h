#pragma once
void HQ_ConsoleInit(void);
/* LVGL task only: queued button handling and snapshot diagnostic reads share
 * the view's lifetime; console callbacks never inspect its graph directly. */
void HQ_ConsolePoll(void);
