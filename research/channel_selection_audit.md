# CAD assembly channel selection audit

## Question and stopping rule

The search question is: which stable internet channels can supply licensed, real multi-part mechanical assemblies in STEP/B-Rep form, and which metadata can cheaply predict sector, component content, repetition and assembly likelihood before a complete download?

Search stopped after all six source families below had at least one evaluated channel, the next searches mostly repeated already represented repositories or returned isolated parts/meshes, and the remaining gaps were explicit rather than hidden. The catalog retains 24 channels: automated primary sources, conditional/manual sources, metadata-only sources and screened-out negative controls.

## Source universe searched

1. DOI and research repositories: DataCite, Zenodo, Mendeley Data, Dryad, OSF and Figshare.
2. Government and standards libraries: NIST MBE PMI, STEP Tools and CAx-IF.
3. Cloud/native CAD: Onshape and Autodesk Fusion Gallery.
4. Supplier and community CAD: 3D ContentCentral, GrabCAD, 3Dfindit/CADENAS, TraceParts and CAD Exchanger.
5. Open-hardware forges: Wikifactory, CERN OHWR and GitLab.
6. ML/general portals: MERL AssemblyBench, Hugging Face, Kaggle, NASA 3D and SampleFile.

## Admission evidence ladder

No source is called a verified assembly merely because its title says “assembly”. Evidence is accumulated in this order:

1. Repository metadata: title, abstract, engineering categories, license and stable identifier.
2. File-tree evidence: `.step`/`.stp`, native assembly formats, BOM/parts-list files, subassembly folders and file sizes.
3. Bounded transport probe: HTTP success, STEP header, ZIP central-directory names, `PRODUCT` count and `NEXT_ASSEMBLY_USAGE_OCCURRENCE` count.
4. Full structural admission, performed only for selected candidates: OCCT parse and minimum Solid count.
5. Expensive grouping/classification, performed only after the previous gates pass.

The first three stages are the new low-cost pre-screen. They do not replace OCCT admission or geometric classification.

## Verified results

- Nine direct URLs were successfully range-read: one Mendeley STEP, five Zenodo STEP/ZIP records and three STEP Tools assemblies.
- All seven sampled direct STEP files exposed an `ISO-10303-21` header.
- All three STEP Tools AS1 files exposed 9 `PRODUCT` records and 13 assembly-occurrence records in the bounded sample.
- The generated-reassembly ZIP exposed 129 STEP entries in its sampled central directory; the cadog evaluation ZIP exposed 9 STEP entries in the sampled directory.
- The bounded head/tail sample found 141 `PRODUCT` records in the Mendeley printer and 285 assembly-occurrence records in the LBNL raft. These counts are sample evidence, not authoritative BOM quantities.
- Mendeley anonymous APIs exposed the 106,602,778-byte CoreXY printer STEP, its SHA-256, its BOM, and a public download URL without downloading the model.
- A live Mendeley discovery test for fluid-power terms returned six real STEP files, including a gear pump and four flowmeters. All stayed at low assembly confidence, so none was automatically staged as a complete assembly. This is a desired rejection, not a discovery failure.
- The final 12-query integration run completed seven provider/type queries and failed five: four GitHub searches lacked a token and one Zenodo cutting-tool query hit the 30-second hard deadline. Every outcome is retained in `channel_search_attempts.csv`; no failure was replaced by an unrecorded source.

## Selection and deferral decisions

- Primary automated channels: DataCite, Zenodo and Mendeley Data. They combine search, rights metadata, file manifests and stable downloads.
- Primary validation channels: NIST and STEP Tools. Their breadth is small, but their assembly/product-structure evidence is authoritative and cheap to inspect.
- Large metadata-first channel: Dryad AutoMate. Download assembly graphs/metadata before the 13.21 GB STEP archive.
- Conditional channel: Onshape. It has excellent native assembly evidence but requires credentials and asynchronous STEP export.
- Manual targeted channels: 3D ContentCentral, GrabCAD, CADENAS/3Dfindit, TraceParts and CAD Exchanger. Use only when the page proves a multi-component configured product; do not crawl their standard-part catalogs.
- Metadata-only until format verification: Autodesk Fusion Gallery, MERL AssemblyBench, Hugging Face and Kaggle.
- Screened out for the current corpus: NASA 3D and SampleFile because the observed offerings are primarily meshes, tiny synthetic examples or isolated parts.

## Known gaps

- The strongest unresolved semantic gap is a full valve/pump/cylinder assembly with repeated fasteners and an explicit reusable license. The new discovery adapter finds fluid components but correctly refuses to treat them as assemblies.
- Cutting-tool evidence currently relies mainly on the ScarfingTool; at least one independent tool-holder/cutter assembly is still needed.
- Metadata component labels are hypotheses. A page can mention a valve in a test setup without embedding the valve geometry, so human review or STEP structure remains required before acquisition.
- Login-only portals cannot be claimed as reproducibly downloadable by the unattended pipeline.
