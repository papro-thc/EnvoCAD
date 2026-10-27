- **Kontrola F7: počet pólů a spojení N s PE** – `pole_count`: do přístroje vede víc fází, než má pólů (u proudového
  chrániče fáze + N) – např. chránič 1+N zapojený žilami L1 L2 L3 N nebo jistič 1p na vodiči s L1–L3; N kolem
  jističe je v pořádku. `n_pe_join`: v uzlu se potkává vodič jen s N a vodič jen s PE – v síti TN-S se N a PE
  v rozvaděči nespojují. Test `test_checks_poles_npe.py`.
