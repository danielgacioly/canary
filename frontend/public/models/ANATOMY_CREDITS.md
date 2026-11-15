# Credits for anatomy.glb

`anatomy.glb` holds the bones and organs of the hologram. It is an adaptation of **BodyParts3D**:

> BodyParts3D, (c) The Database Center for Life Science, licensed under CC Attribution-Share Alike 2.1 Japan.
> https://dbarchive.biosciencedbc.jp/en/bodyparts3d/

- Source data: BodyParts3D release 4.0, "PART-OF" OBJ files (`partof_BP3D_4.0_obj_99.zip`) with the tables `partof_parts_list_e.txt` and `partof_element_parts.txt`, downloaded from the DBCLS archive without any login.
- Licence of the files: each OBJ file carries the header "Creative Commons Attribution-Share Alike 2.1 Japan". The archive's licence page was updated in 2025 and now states CC Attribution 4.0 International. We follow the stricter notice that is inside the data files.
- **Share-alike:** `anatomy.glb` is a derivative of that data, so it stays under **CC BY-SA 2.1 Japan** (or a later compatible CC BY-SA licence). Anyone who copies or adapts the file must give the credit above, say that it was changed, and keep the same licence. The licence applies to the model file, not to the rest of the Canary source code.
- What we changed (all of it done by `tools/build_anatomy_model.py`): selected the elements of each organ and bone; converted millimetres to metres and the axes to the MakeHuman frame; moved and warped them to sit inside `body.glb` (a height-preserving slice warp for the trunk and head, one similarity transform per bone chain for arms and legs); built a smooth lung surface around the airways and pulmonary vessels (BodyParts3D has the airways and vessels of the lungs, not a lobe surface); reduced the triangle count (about 228,000 in total) and compressed the file with meshopt.
- **Not from BodyParts3D:** the spleen, a small procedural ellipsoid (BodyParts3D has no spleen), and everything that `anatomy.ts` draws as tubes (limb arteries and nerves).
- BodyParts3D is a model of one adult male body. The hologram is a readable map of body systems, not a medical atlas, and not a diagnostic tool.

The outer body, `body.glb` and `joints.json`, comes from the MakeHuman base mesh (CC0 1.0).
