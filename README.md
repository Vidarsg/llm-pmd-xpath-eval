# LLM-Generated PMD XPath Rule Evaluation

This repository contains the experimental framework used to evaluate LLM-generated XPath rules for PMD against real-world Java codebases.

---

## Overview

This project evaluates whether large language models (LLMs) can:

- Generate syntactically valid PMD XPath rules  
- Produce behaviorally similar rules compared to official PMD rules  
- Generalize across real-world Java repositories  

The framework:

- Wraps generated XPath expressions into valid PMD rulesets  
- Executes PMD programmatically  
- Extracts violations and error metadata  
- Records rule-level results for large-scale evaluation  

---

## Tooling

- **PMD version:** 7.20.0  
- **Java version:** 17  
- **Rule type:** PMD Java XPath-based rules  

---
