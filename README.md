# Strmgen
Strmgen is a Python script used to generate VOD files for Dispatcharr

You will need to rename config_base.json to config.json and update with your settings for the scripts to work.

Volume Mappings:
	•	Host /mnt/user/appdata/strmgen/config → Container /app/strmgen/config
	•	Host /mnt/user/appdata/strmgen/logs   → Container /app/strmgen/logs
	•	Host /mnt/user/media/vod             → Container /volumes/data/media/vod

Host Port: 8808    