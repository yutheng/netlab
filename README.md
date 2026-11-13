# netlab

My lab portfolio for WIC2005 Programmable Networks, Semester I 2026/2027.
Each week's page is published from `docs/` with GitHub Pages:

- Week 6 — multi-tenant VXLAN overlay: https://yutheng.github.io/netlab/week6/

All addresses come from the last digits of my student ID (10.15.0.0/16). Only the last
four digits appear in this repository.

## AI use

**Appendix 2(b): AI Use Declaration Form for Assessments (Students)**

| | |
|---|---|
| Semester/Session | Semester I, 2026/2027 |
| Programme Name | Computer System and Network |
| Course Code & Name | WIC2005 Programmable Networks |
| Assignment/Assessment Title | Lab portfolio assignments (one section per week below) |

My name and matric number are not included because this repository is public.

☑ I hereby declare that part of this assignment submission contains contributions from AI
software and is in line with acceptable use as stated in the Declaration Form for the Use
of AI in T&L Activities [Appendix 2(a)], briefing or assignment guidelines, and consistent
with good academic practice.

The content can still be considered as my own work. I understand that as long as my usage
falls under "acceptable use" as defined in the assessment summary/guidelines, this
declaration will have no direct impact on the grade awarded.

I acknowledge the use of software as follows, for each assignment:

### Week 6 assignment: Overlay your own data centre (Level 3, Open)

| NO. | ITEM | USAGE |
|---|---|---|
| 1 | Claude (Anthropic): code in `build_overlay.py` | **Level 3.** Claude wrote the first versions of `tenant_commands()` and `check_mtu()` from their docstrings. I ran and tested them on my own design: every VM reached the VMs of its own tenant, the black-hole design was refused, and both MTU fixes were accepted. |
| 2 | Claude (Anthropic): explanations and troubleshooting | **Level 3.** Claude explained the lab concepts (namespaces, veth pairs, VXLAN encapsulation, MTU limits, flood-and-learn, EVPN, data plane vs control plane, the lecture's `vtep.p4`) and helped me interpret my outputs. It also helped me find why my first tcpdump captures were empty and why pasting command blocks into Mininet lost lines. |
| 3 | Claude (Anthropic): design review and evidence commands | **Level 3.** The design and its scenario (buildings as tenants, rooms as VMs) are my own. Claude checked it against the requirements and suggested changing it further from the starting file, for example by adding a fourth hypervisor. Claude also adapted the D5 evidence commands to my names and addresses. I ran every command and saved all output in `evidence6/` myself. |
| 4 | Claude (Anthropic): written answers in `page6.yaml` | **Level 3.** For the isolation, flood-and-learn and MTU answers, I wrote rough drafts, and Claude corrected technical mistakes and rephrased them into paragraphs. The design and P4 answers were drafted by Claude from my design, my scenario and an explanation of `vtep.p4`. I checked every answer against my own evidence and chose the final MTU fix myself. |

My overlay design, every run in Mininet, all evidence in `evidence6/` and the choice of MTU
fix are my own, and I can explain and defend everything submitted.
