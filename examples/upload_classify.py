"""Upload -> classify -> show: the classic Gradio ML demo, now in indah (ADR-0017).

Upload an image; a real, small, CPU-friendly classifier predicts a label; the page
shows the image back, the prediction, and a downloadable report. ``classify`` is a
plain function behind a plain handler (ADR-0009): the model call is the only thing
that would change to swap in a different classifier, the rest of the app is unchanged.

The model is MobileNetV2 (ImageNet-1000), run with ``onnxruntime`` on CPU -- no GPU
needed, unlike the diffusion demo. Weights (~13 MB) download once from the Hugging
Face Hub on first use and are cached; a cold-started Fly machine pays that download
once per boot, then serves inference from RAM. ``onnxruntime``/``Pillow`` are this
demo's own dependencies (not indah's), imported lazily inside ``classify`` so the
rest of the module -- and indah's own test suite -- needs neither installed.

Each viewer gets an isolated session (``session_factory``, ADR-0010), so one
person's upload and result are private to their tab. Runs on Tier 0 (SSE + POST),
so it works behind Colab's proxy.

Run it with:  python examples/upload_classify.py
Then open the URL and upload an image. No Node, at install or at runtime.
"""

import asyncio
import base64

import indah
from indah import (
    Card,
    Column,
    Download,
    DownloadFile,
    Image,
    Session,
    Signal,
    Spinner,
    Text,
    Upload,
    UploadedFile,
    create_app,
)

# The 1000 ImageNet class names MobileNetV2's output index maps to, in the standard
# ILSVRC2012 order (from onnx/models' synset.txt) -- embedded here, not fetched at
# request time or read from a sibling file, because the Colab notebook generator
# (deploy/colab/make_colab.py) inlines only this module's own source text.
IMAGENET_LABELS: list[str] = (
    "tench,goldfish,great white shark,tiger shark,hammerhead,electric ray,stingray,cock,hen,"
    "ostrich,brambling,goldfinch,house finch,junco,indigo bunting,robin,bulbul,jay,magpie,"
    "chickadee,water ouzel,kite,bald eagle,vulture,great grey owl,European fire salamander,"
    "common newt,eft,spotted salamander,axolotl,bullfrog,tree frog,tailed frog,loggerhead,"
    "leatherback turtle,mud turtle,terrapin,box turtle,banded gecko,common iguana,"
    "American chameleon,whiptail,agama,frilled lizard,alligator lizard,Gila monster,green lizard,"
    "African chameleon,Komodo dragon,African crocodile,American alligator,triceratops,"
    "thunder snake,ringneck snake,hognose snake,green snake,king snake,garter snake,water snake,"
    "vine snake,night snake,boa constrictor,rock python,Indian cobra,green mamba,sea snake,"
    "horned viper,diamondback,sidewinder,trilobite,harvestman,scorpion,"
    "black and gold garden spider,barn spider,garden spider,black widow,tarantula,wolf spider,"
    "tick,centipede,black grouse,ptarmigan,ruffed grouse,prairie chicken,peacock,quail,partridge,"
    "African grey,macaw,sulphur-crested cockatoo,lorikeet,coucal,bee eater,hornbill,hummingbird,"
    "jacamar,toucan,drake,red-breasted merganser,goose,black swan,tusker,echidna,platypus,"
    "wallaby,koala,wombat,jellyfish,sea anemone,brain coral,flatworm,nematode,conch,snail,slug,"
    "sea slug,chiton,chambered nautilus,Dungeness crab,rock crab,fiddler crab,king crab,"
    "American lobster,spiny lobster,crayfish,hermit crab,isopod,white stork,black stork,"
    "spoonbill,flamingo,little blue heron,American egret,bittern,crane,limpkin,"
    "European gallinule,American coot,bustard,ruddy turnstone,red-backed sandpiper,redshank,"
    "dowitcher,oystercatcher,pelican,king penguin,albatross,grey whale,killer whale,dugong,"
    "sea lion,Chihuahua,Japanese spaniel,Maltese dog,Pekinese,Shih-Tzu,Blenheim spaniel,papillon,"
    "toy terrier,Rhodesian ridgeback,Afghan hound,basset,beagle,bloodhound,bluetick,"
    "black-and-tan coonhound,Walker hound,English foxhound,redbone,borzoi,Irish wolfhound,"
    "Italian greyhound,whippet,Ibizan hound,Norwegian elkhound,otterhound,Saluki,"
    "Scottish deerhound,Weimaraner,Staffordshire bullterrier,American Staffordshire terrier,"
    "Bedlington terrier,Border terrier,Kerry blue terrier,Irish terrier,Norfolk terrier,"
    "Norwich terrier,Yorkshire terrier,wire-haired fox terrier,Lakeland terrier,Sealyham terrier,"
    "Airedale,cairn,Australian terrier,Dandie Dinmont,Boston bull,miniature schnauzer,"
    "giant schnauzer,standard schnauzer,Scotch terrier,Tibetan terrier,silky terrier,"
    "soft-coated wheaten terrier,West Highland white terrier,Lhasa,flat-coated retriever,"
    "curly-coated retriever,golden retriever,Labrador retriever,Chesapeake Bay retriever,"
    "German short-haired pointer,vizsla,English setter,Irish setter,Gordon setter,"
    "Brittany spaniel,clumber,English springer,Welsh springer spaniel,cocker spaniel,"
    "Sussex spaniel,Irish water spaniel,kuvasz,schipperke,groenendael,malinois,briard,kelpie,"
    "komondor,Old English sheepdog,Shetland sheepdog,collie,Border collie,Bouvier des Flandres,"
    "Rottweiler,German shepherd,Doberman,miniature pinscher,Greater Swiss Mountain dog,"
    "Bernese mountain dog,Appenzeller,EntleBucher,boxer,bull mastiff,Tibetan mastiff,"
    "French bulldog,Great Dane,Saint Bernard,Eskimo dog,malamute,Siberian husky,dalmatian,"
    "affenpinscher,basenji,pug,Leonberg,Newfoundland,Great Pyrenees,Samoyed,Pomeranian,chow,"
    "keeshond,Brabancon griffon,Pembroke,Cardigan,toy poodle,miniature poodle,standard poodle,"
    "Mexican hairless,timber wolf,white wolf,red wolf,coyote,dingo,dhole,African hunting dog,"
    "hyena,red fox,kit fox,Arctic fox,grey fox,tabby,tiger cat,Persian cat,Siamese cat,"
    "Egyptian cat,cougar,lynx,leopard,snow leopard,jaguar,lion,tiger,cheetah,brown bear,"
    "American black bear,ice bear,sloth bear,mongoose,meerkat,tiger beetle,ladybug,ground beetle,"
    "long-horned beetle,leaf beetle,dung beetle,rhinoceros beetle,weevil,fly,bee,ant,grasshopper,"
    "cricket,walking stick,cockroach,mantis,cicada,leafhopper,lacewing,dragonfly,damselfly,"
    "admiral,ringlet,monarch,cabbage butterfly,sulphur butterfly,lycaenid,starfish,sea urchin,"
    "sea cucumber,wood rabbit,hare,Angora,hamster,porcupine,fox squirrel,marmot,beaver,"
    "guinea pig,sorrel,zebra,hog,wild boar,warthog,hippopotamus,ox,water buffalo,bison,ram,"
    "bighorn,ibex,hartebeest,impala,gazelle,Arabian camel,llama,weasel,mink,polecat,"
    "black-footed ferret,otter,skunk,badger,armadillo,three-toed sloth,orangutan,gorilla,"
    "chimpanzee,gibbon,siamang,guenon,patas,baboon,macaque,langur,colobus,proboscis monkey,"
    "marmoset,capuchin,howler monkey,titi,spider monkey,squirrel monkey,Madagascar cat,indri,"
    "Indian elephant,African elephant,lesser panda,giant panda,barracouta,eel,coho,rock beauty,"
    "anemone fish,sturgeon,gar,lionfish,puffer,abacus,abaya,academic gown,accordion,"
    "acoustic guitar,aircraft carrier,airliner,airship,altar,ambulance,amphibian,analog clock,"
    "apiary,apron,ashcan,assault rifle,backpack,bakery,balance beam,balloon,ballpoint,Band Aid,"
    "banjo,bannister,barbell,barber chair,barbershop,barn,barometer,barrel,barrow,baseball,"
    "basketball,bassinet,bassoon,bathing cap,bath towel,bathtub,beach wagon,beacon,beaker,"
    "bearskin,beer bottle,beer glass,bell cote,bib,bicycle-built-for-two,bikini,binder,"
    "binoculars,birdhouse,boathouse,bobsled,bolo tie,bonnet,bookcase,bookshop,bottlecap,bow,"
    "bow tie,brass,brassiere,breakwater,breastplate,broom,bucket,buckle,bulletproof vest,"
    "bullet train,butcher shop,cab,caldron,candle,cannon,canoe,can opener,cardigan,car mirror,"
    "carousel,carpenter's kit,carton,car wheel,cash machine,cassette,cassette player,castle,"
    "catamaran,CD player,cello,cellular telephone,chain,chainlink fence,chain mail,chain saw,"
    "chest,chiffonier,chime,china cabinet,Christmas stocking,church,cinema,cleaver,"
    "cliff dwelling,cloak,clog,cocktail shaker,coffee mug,coffeepot,coil,combination lock,"
    "computer keyboard,confectionery,container ship,convertible,corkscrew,cornet,cowboy boot,"
    "cowboy hat,cradle,crane,crash helmet,crate,crib,Crock Pot,croquet ball,crutch,cuirass,dam,"
    "desk,desktop computer,dial telephone,diaper,digital clock,digital watch,dining table,"
    "dishrag,dishwasher,disk brake,dock,dogsled,dome,doormat,drilling platform,drum,drumstick,"
    "dumbbell,Dutch oven,electric fan,electric guitar,electric locomotive,entertainment center,"
    "envelope,espresso maker,face powder,feather boa,file,fireboat,fire engine,fire screen,"
    "flagpole,flute,folding chair,football helmet,forklift,fountain,fountain pen,four-poster,"
    "freight car,French horn,frying pan,fur coat,garbage truck,gasmask,gas pump,goblet,go-kart,"
    "golf ball,golfcart,gondola,gong,gown,grand piano,greenhouse,grille,grocery store,guillotine,"
    "hair slide,hair spray,half track,hammer,hamper,hand blower,hand-held computer,handkerchief,"
    "hard disc,harmonica,harp,harvester,hatchet,holster,home theater,honeycomb,hook,hoopskirt,"
    "horizontal bar,horse cart,hourglass,iPod,iron,jack-o'-lantern,jean,jeep,jersey,"
    "jigsaw puzzle,jinrikisha,joystick,kimono,knee pad,knot,lab coat,ladle,lampshade,laptop,"
    "lawn mower,lens cap,letter opener,library,lifeboat,lighter,limousine,liner,lipstick,Loafer,"
    "lotion,loudspeaker,loupe,lumbermill,magnetic compass,mailbag,mailbox,maillot,maillot,"
    "manhole cover,maraca,marimba,mask,matchstick,maypole,maze,measuring cup,medicine chest,"
    "megalith,microphone,microwave,military uniform,milk can,minibus,miniskirt,minivan,missile,"
    "mitten,mixing bowl,mobile home,Model T,modem,monastery,monitor,moped,mortar,mortarboard,"
    "mosque,mosquito net,motor scooter,mountain bike,mountain tent,mouse,mousetrap,moving van,"
    "muzzle,nail,neck brace,necklace,nipple,notebook,obelisk,oboe,ocarina,odometer,oil filter,"
    "organ,oscilloscope,overskirt,oxcart,oxygen mask,packet,paddle,paddlewheel,padlock,"
    "paintbrush,pajama,palace,panpipe,paper towel,parachute,parallel bars,park bench,"
    "parking meter,passenger car,patio,pay-phone,pedestal,pencil box,pencil sharpener,perfume,"
    "Petri dish,photocopier,pick,pickelhaube,picket fence,pickup,pier,piggy bank,pill bottle,"
    "pillow,ping-pong ball,pinwheel,pirate,pitcher,plane,planetarium,plastic bag,plate rack,plow,"
    "plunger,Polaroid camera,pole,police van,poncho,pool table,pop bottle,pot,potter's wheel,"
    "power drill,prayer rug,printer,prison,projectile,projector,puck,punching bag,purse,quill,"
    "quilt,racer,racket,radiator,radio,radio telescope,rain barrel,recreational vehicle,reel,"
    "reflex camera,refrigerator,remote control,restaurant,revolver,rifle,rocking chair,"
    "rotisserie,rubber eraser,rugby ball,rule,running shoe,safe,safety pin,saltshaker,sandal,"
    "sarong,sax,scabbard,scale,school bus,schooner,scoreboard,screen,screw,screwdriver,seat belt,"
    "sewing machine,shield,shoe shop,shoji,shopping basket,shopping cart,shovel,shower cap,"
    "shower curtain,ski,ski mask,sleeping bag,slide rule,sliding door,slot,snorkel,snowmobile,"
    "snowplow,soap dispenser,soccer ball,sock,solar dish,sombrero,soup bowl,space bar,"
    "space heater,space shuttle,spatula,speedboat,spider web,spindle,sports car,spotlight,stage,"
    "steam locomotive,steel arch bridge,steel drum,stethoscope,stole,stone wall,stopwatch,stove,"
    "strainer,streetcar,stretcher,studio couch,stupa,submarine,suit,sundial,sunglass,sunglasses,"
    "sunscreen,suspension bridge,swab,sweatshirt,swimming trunks,swing,switch,syringe,table lamp,"
    "tank,tape player,teapot,teddy,television,tennis ball,thatch,theater curtain,thimble,"
    "thresher,throne,tile roof,toaster,tobacco shop,toilet seat,torch,totem pole,tow truck,"
    "toyshop,tractor,trailer truck,tray,trench coat,tricycle,trimaran,tripod,triumphal arch,"
    "trolleybus,trombone,tub,turnstile,typewriter keyboard,umbrella,unicycle,upright,vacuum,vase,"
    "vault,velvet,vending machine,vestment,viaduct,violin,volleyball,waffle iron,wall clock,"
    "wallet,wardrobe,warplane,washbasin,washer,water bottle,water jug,water tower,whiskey jug,"
    "whistle,wig,window screen,window shade,Windsor tie,wine bottle,wing,wok,wooden spoon,wool,"
    "worm fence,wreck,yawl,yurt,web site,comic book,crossword puzzle,street sign,traffic light,"
    "book jacket,menu,plate,guacamole,consomme,hot pot,trifle,ice cream,ice lolly,French loaf,"
    "bagel,pretzel,cheeseburger,hotdog,mashed potato,head cabbage,broccoli,cauliflower,zucchini,"
    "spaghetti squash,acorn squash,butternut squash,cucumber,artichoke,bell pepper,cardoon,"
    "mushroom,Granny Smith,strawberry,orange,lemon,fig,pineapple,banana,jackfruit,custard apple,"
    "pomegranate,hay,carbonara,chocolate sauce,dough,meat loaf,pizza,potpie,burrito,red wine,"
    "espresso,cup,eggnog,alp,bubble,cliff,coral reef,geyser,lakeside,promontory,sandbar,seashore,"
    "valley,volcano,ballplayer,groom,scuba diver,rapeseed,daisy,yellow lady's slipper,corn,acorn,"
    "hip,buckeye,coral fungus,agaric,gyromitra,stinkhorn,earthstar,hen-of-the-woods,bolete,ear,"
    "toilet tissue"
).split(",")

# The MobileNetV2-12 ONNX export from the (Apache-2.0) ONNX Model Zoo, mirrored on the
# Hugging Face Hub. ~13 MB; downloaded once via huggingface_hub and cached like any HF
# model weights (~/.cache/huggingface), the same pattern chatbot.py uses for transformers.
_MODEL_REPO = "onnxmodelzoo/mobilenetv2-12"
_MODEL_FILE = "mobilenetv2-12.onnx"

_IMAGENET_MEAN = (0.485, 0.456, 0.406)
_IMAGENET_STD = (0.229, 0.224, 0.225)

_session = None  # lazily-loaded onnxruntime.InferenceSession, cached across calls


def _load_session():
    """Download (once, cached) and load the ONNX model. Lazy so importing this
    module -- and indah's own test suite -- never requires onnxruntime installed."""
    global _session
    if _session is None:
        from huggingface_hub import hf_hub_download
        from onnxruntime import InferenceSession

        path = hf_hub_download(repo_id=_MODEL_REPO, filename=_MODEL_FILE)
        _session = InferenceSession(path, providers=["CPUExecutionProvider"])
    return _session


def classify(data: bytes) -> tuple[str, float]:
    """Classify an image's raw bytes with MobileNetV2, run live on CPU.

    Decodes ``data`` with Pillow, resizes to MobileNetV2's expected 224x224 and
    applies standard ImageNet normalization, then runs one onnxruntime inference and
    returns the top-1 ``(label, confidence)``. A real GPU model (torch/transformers)
    would drop in behind this same signature with the rest of the app unchanged
    (ADR-0009); this one is deliberately CPU-only and light enough to run per-request
    on the shared Fly gallery box.
    """
    import io

    import numpy as np
    from PIL import Image as PILImage

    image = PILImage.open(io.BytesIO(data)).convert("RGB").resize((224, 224))
    pixels = np.asarray(image, dtype=np.float32) / 255.0
    pixels = (pixels - _IMAGENET_MEAN) / _IMAGENET_STD  # numpy promotes this to float64
    batch = pixels.transpose(2, 0, 1)[np.newaxis, ...].astype(np.float32)  # HWC -> NCHW

    session = _load_session()
    (logits,) = session.run(None, {"input": batch})
    exp = np.exp(logits[0] - logits[0].max())
    probs = exp / exp.sum()
    top = int(probs.argmax())
    return IMAGENET_LABELS[top], float(probs[top])


def _data_uri(file: UploadedFile) -> str:
    """The uploaded image bytes as a data: URI, so the shell can show it back."""
    mime = file.content_type or "image/png"
    return f"data:{mime};base64," + base64.b64encode(file.data).decode("ascii")


def build_session() -> Session:
    """A fresh per-viewer graph: upload an image, classify it, show the result."""
    preview: Signal[str] = Signal("")
    result: Signal[str] = Signal("")
    report: Signal = Signal(None)
    busy: Signal[bool] = Signal(False)

    async def on_upload(file: UploadedFile) -> None:
        busy.set(True)
        result.set("")
        report.set(None)
        preview.set(_data_uri(file))
        # onnxruntime inference is synchronous CPU work; run it off the event loop so
        # it never blocks the UI (ADR-0011), the same guarantee chatbot.py's
        # asyncio.to_thread call gives its (also synchronous, thread-run) generation.
        label, confidence = await asyncio.to_thread(classify, file.data)
        result.set(f"Prediction: **{label}**  \nConfidence: **{confidence:.0%}**")
        summary = (
            f"file: {file.filename}\n"
            f"size: {file.size} bytes\n"
            f"prediction: {label}\n"
            f"confidence: {confidence:.2f}\n"
        )
        report.set(
            DownloadFile(summary.encode(), filename="prediction.txt", media_type="text/plain")
        )
        busy.set(False)

    return Session(
        Column(
            children=[
                Text(
                    "# Image classifier\n\n"
                    "Upload an image and a real MobileNetV2 model predicts a label, run "
                    "live on CPU. Each tab is its own session, so your upload and result "
                    "stay private to it.",
                    markdown=True,
                ),
                Card(
                    title="Input",
                    children=[
                        Upload(on_upload, accept="image/*", label="Upload an image"),
                        Spinner(active=busy, label="Classifying..."),
                    ],
                ),
                Card(
                    title="Result",
                    children=[
                        Image(preview, alt="uploaded image"),
                        Text(lambda: result.value or "_No prediction yet._", markdown=True),
                        Download(report, label="Download report", filename="prediction.txt"),
                    ],
                ),
            ]
        )
    )


# Module-level ASGI app for hosting (HF Spaces / uvicorn, ADR-0023).
app = create_app(session_factory=build_session)


if __name__ == "__main__":
    indah.launch(app)
