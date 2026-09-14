from pathlib import Path

src=Path("scripts/deep_framlingham_recovery.py").read_text()
src=src.replace('recovered/framlingham-castle','recovered/kenilworth-castle')
src=src.replace('FramlinghamArchiveRecovery','KenilworthArchiveRecovery')
src=src.replace('TS="20220826211200"','TS="20220826212821"')
src=src.replace('Framlingham Castle archived original image','Kenilworth Castle archived original image')
src=src.replace('page-audit/framlingham-castle.json','page-audit/kenilworth-castle.json')
src=src.replace('"name":"Framlingham Castle"','"name":"Kenilworth Castle"')
src=src.replace('"slug":"framlingham-castle"','"slug":"kenilworth-castle"')

a=src.index("NAMED={")
b=src.index("ORDER=list(NAMED)+",a)
b=src.index("\n",b)+1
block='''NAMED={
 "kenilworth_castle1":"http://www.castlesfortsbattles.co.uk/Kenilworth_Castle1.JPG",
 "kenilworth_castle9":"http://www.castlesfortsbattles.co.uk/Kenilworth_Castle9.JPG",
 "kenilworth_castle15":"http://www.castlesfortsbattles.co.uk/Kenilworth_Castle15.jpg",
}
GALLERY=[
 "dc20d5b234f9","267af4eccf9b","7cd4ac90e6b4","cfda0b0df50a","79ec23415d55",
 "c092400f91eb","88e2a1bbb494","4e73e53f9d96","6a16fdfe86c4","eb2e38e12c08",
 "9e9bfb929265","ff7a7893da34","28181a0a6a1c"
]
ORDER=["kenilworth_castle1","kenilworth_castle9"]+["gallery_"+x for x in GALLERY]+["kenilworth_castle15"]
'''
src=src[:a]+block+src[b:]
Path("/tmp/deep_kenilworth.py").write_text(src)
