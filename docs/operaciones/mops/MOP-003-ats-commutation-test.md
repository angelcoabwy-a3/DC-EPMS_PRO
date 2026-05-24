# MOP-003 — Utility: Prueba de Conmutación en Vacío y con Carga en ATS (Automatic Transfer Switch)

**Asset Category:** ATS / Utility / Generator · **Work Mode:** Live
(trabajo en vivo cerca de equipo energizado; NO se aplica LOTO al
tablero ATS durante la prueba). **Compliance:** CSA Z462-24, NFPA 110,
NFPA 70E §130.

---

## 1. Alcance y Objetivo


* **Identificador (Tag):** ATS-A or ATS-B
* **Estado Final Esperado:** ATS operativo + lógica de transferencia validada + generador en modo Auto + UPS en flotación

Verificar la integridad operativa y la lógica de control del Tablero
de Transferencia Automática, asegurando que la carga crítica sea
asumida por el generador de respaldo frente a una simulación de
pérdida de acometida principal (Utility).

**Equipo objetivo:** ATS principal del Building correspondiente +
generador de emergencia asociado. **Ubicación:** sala eléctrica
principal + caseta del generador.

---

## 2. Evaluación de Impacto y Riesgos


- **Vector Eléctrico (Arc Flash Cat 4 durante conmutación mecánica)**

- **Impacto en carga IT:** durante la prueba con carga, la totalidad
  del Path bajo ese ATS pasa por una transición Utility → Generator
  (y de vuelta). La carga IT lo absorbe vía UPS — el bus crítico
  debe mantenerse estable; cualquier `sag` queda mitigado por las
  baterías. Verificar el SoC de los UPS antes de iniciar.
- **Nivel de energía incidente:** **alto (Arc Flash Category 4)** en
  el tablero ATS debido a la concentración de energía. Toda la
  maniobra es operada desde el HMI / controlador; NO se abre ninguna
  cubierta del tablero durante la prueba.
- **Dependencias aguas arriba:** Utility commercial + generador de
  emergencia (combustible, baterías de arranque, sistema de
  enfriamiento del motor).
- **Dependencias aguas abajo:** UPS, PDUs, racks. Una transición
  fallida (Utility se corta y el generador no asume) significa que
  la carga IT depende exclusivamente del autonomía de baterías de
  los UPS hasta que se restaure la red — ventana típica 10-15 min.
- **Coordinación mecánica:** los arranques simultáneos pesados
  (chillers / CRACs) durante la transición pueden causar `sags`
  severos en la rama del generador → coordinar con HVAC.

---

## 3. Requisitos Previos (Prerrequisitos)

- Coordinación con el equipo de infraestructura mecánica (HVAC) para
  prevenir arranques simultáneos pesados (chillers/CRACs) durante la
  transición.
- El personal debe permanecer **fuera del límite de aproximación
  restringida** del tablero ATS durante el momento exacto de la
  conmutación mecánica.
- **PPE Categoría 4** requerido debido a la alta concentración de
  energía en tableros principales (per **CSA Z462-24** sección
  130.7(C)).
- **Combustible del generador ≥ 80%** verificado antes de iniciar.
- **PTW (Permiso de Trabajo)** firmado por el Manager on Duty + NOC
  notificado del inicio + de la finalización.
- **Herramientas:** cronómetro calibrado, multímetro calibrado para
  validar voltaje/frecuencia en el HMI, radio de comunicación con
  el operador del cuarto de generador.
- Personal mínimo: técnico ejecutante en sala ATS + supervisor en
  el HMI (Maker + Checker — Cuatro Ojos).

> **Nota — no LOTO:** esta prueba es una maniobra operacional en vivo;
> el ATS y el generador permanecen energizados. La salvaguarda
> primaria es el **respeto al límite de aproximación restringida**
> + PPE Cat 4, NO el aislamiento.

- **Operabilidad de Agentes (Health Check):** confirmar que el Agente Revisor (Checker) y los Discipline AIs (HVAC AI / Electrical AI según vector) están `ONLINE` y reportando telemetría vía **MCP** antes de iniciar la maniobra.

---

## 4. Lista de Pasos Secuenciales

> Cada paso requiere doble firma (Cuatro Ojos / Maker-Checker).

1. Verificar que el generador de emergencia se encuentre en modo
   **"Auto"** sin alarmas preexistentes y con niveles de combustible
   superiores al 80%.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

2. Observar el controlador del ATS y confirmar que la fuente activa
   es "Utility" y el voltaje/frecuencia están dentro de los
   parámetros nominales.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

3. Ejecutar el comando **"Test Without Load"** (Prueba en vacío)
   desde la interfaz del ATS. Verificar que el generador arranca,
   alcanza el voltaje y la frecuencia nominal en **menos de 10
   segundos**, pero el contactor NO realiza la transferencia.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

4. Detener la prueba en vacío y permitir que el generador ejecute su
   ciclo de enfriamiento (Cool down) y se apague.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

5. Ejecutar el comando **"Test With Load"** (Prueba con carga)
   simulando una pérdida de red.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

6. Cronometrar la secuencia: el generador debe arrancar y, tras
   estabilizarse, el ATS debe accionar mecánicamente la
   transferencia aislando la "Utility" y conectando la carga al
   generador. **Personal fuera del límite de aproximación restringida
   durante la conmutación.**
   `[ ] Técnico: __________  [ ] Supervisor: __________`

   > [HOLD POINT] Verificar V/Hz nominales del generador en HMI antes de la conmutación mecánica.

7. Verificar la estabilidad de voltaje (`sags`) y frecuencia en los
   tableros de distribución aguas abajo tras la conmutación.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

8. Finalizar la prueba en el controlador. El ATS debe monitorear la
   "Utility", realizar la re-transferencia (transición cerrada o
   abierta, según diseño) y enviar la señal de apagado al generador
   tras el ciclo de enfriamiento.
   `[ ] Técnico: __________  [ ] Supervisor: __________`

---

## 5. Plan de Reversión (Back-out Plan)

**Criterios de Aborto:**

- Si al ordenar la prueba con carga el ATS realiza el corte de la red
  principal pero el generador **no asume la carga en un lapso máximo
  de 15 segundos** (o lo estipulado por diseño), abortar la prueba
  inmediatamente forzando el retorno mecánico/eléctrico a "Utility"
  para restaurar el flujo de energía hacia la infraestructura (UPS).
- Si durante el paso 3 el generador no alcanza voltaje/frecuencia
  nominal en < 10 s, abortar antes de pasar al paso 5 (prueba con
  carga); diagnosticar primero el modo "Auto" + combustible +
  baterías de arranque.
- Si el HMI / controlador del ATS muestra alarmas durante la
  transición, abortar; no insistir con re-intentos automáticos.

**Secuencia de Reversión (forzar Utility):**

1. Desde el controlador del ATS, ejecutar el comando manual de
   retorno a "Utility" (transición abierta si la cerrada no
   sincroniza).
2. Confirmar que la carga aguas abajo es alimentada por Utility +
   los UPS retoman flotación.
3. Apagar el generador desde el panel del cuarto de generador
   (Stop + Reset de alarmas tras el ciclo de enfriamiento).
4. Notificar al NOC + Manager on Duty del aborto + causa raíz
   preliminar.
5. Documentar en el WO el comportamiento observado y el diagnóstico
   inicial. La prueba no se vuelve a intentar sin firmar un nuevo
   PTW.

**Ventana de reversión bounded by:** la autonomía de baterías de los
UPS bajo la carga proyectada (~10-15 min típico). Si la reversión
no se completa dentro del 50% de esa ventana, escalar al Manager on
Duty y considerar Emergency Power Off (EOP separado, no este MOP).
