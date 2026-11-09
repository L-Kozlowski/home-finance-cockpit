Home Finance Cockpit - cyan brand assets

Supplied assets were moved from Home_Finance_Cockpit_spojne_logo.
Original source assets used by the build tool remain here; filenames use English names.

wordmark-dark/light.svg: supplied full source wordmarks, with backgrounds.
wordmark-ui-dark/light.svg: transparent, tightly framed derivatives for the UI.
app-icon-16/32/64/128/256/512/1024.png: supplied native-resolution application icons.
app-icon.ico: Windows multi-resolution icon embedding the supplied 16-256 PNG files.

Derived assets can be rebuilt with: python tools/build_brand_assets.py
PDF wordmark and monochrome UI icon derivatives live in reports/.
Rebuild them with python tools/build_report_assets.py. PDF workers tint the icons
without creating Qt widgets or requiring a GUI. Segoe UI is embedded when installed;
other platforms use the existing DejaVu Sans font fallback.

Bar gradient: #55E8FF -> #22D3EE -> #06B6D4, top to bottom.
Background #0B1623; panels #112233; surfaces #1A2B3D; borders #24394D;
inputs #1E3347; text #EDF4FF; secondary text #A8BED5; muted #7B8FA6.
Statuses: success #10B981; warning #F59E0B; error #EF4444; info #3B82F6.
