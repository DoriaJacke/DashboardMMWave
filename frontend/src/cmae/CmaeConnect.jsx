// Ventana para conectar la placa CMAE: Bluetooth, USB o simulada.
// Adaptada de dashboard-cmae/frontend/src/components/ConnectModal.jsx (sin "Reproducir").

import { useEffect, useState } from "react";
import { Alert, Button, Form, ListGroup, Modal, Nav, Spinner } from "react-bootstrap";
import { Bluetooth, FlaskConical, RefreshCw, Search, Usb } from "lucide-react";
import { cmaeApi } from "./api";

const TABS = [
  { id: "ble", label: "Bluetooth", Icon: Bluetooth },
  { id: "uart", label: "USB", Icon: Usb },
  { id: "simulada", label: "Simulada", Icon: FlaskConical },
];

export default function CmaeConnect({ show, onHide }) {
  const [tab, setTab] = useState("ble");
  const [numero, setNumero] = useState("");
  const [puerto, setPuerto] = useState("");
  const [puertos, setPuertos] = useState(null);
  const [placas, setPlacas] = useState(null);
  const [buscando, setBuscando] = useState(false);
  const [formato, setFormato] = useState("BLE");
  const [error, setError] = useState(null);
  const [enviando, setEnviando] = useState(false);

  const cargarPuertos = () =>
    cmaeApi
      .ports()
      .then((lista) => {
        setPuertos(lista);
        // Se propone el puerto que parece ser la placa (CP2102N), si lo hay.
        setPuerto((actual) => {
          if (lista.some((p) => p.puerto === actual)) return actual;
          return (lista.find((p) => p.parece_placa) || lista.find((p) => !p.es_debug) || lista[0])?.puerto || "";
        });
      })
      .catch((e) => setError(e.message));

  // Al abrir: recuerda lo último que se usó y carga los puertos.
  useEffect(() => {
    if (!show) return;
    setError(null);
    setPlacas(null);
    cmaeApi
      .config()
      .then((cfg) => {
        if (TABS.some((t) => t.id === cfg.origen)) setTab(cfg.origen);
        if (cfg.numero) setNumero(String(cfg.numero));
        if (cfg.puerto) setPuerto(cfg.puerto);
      })
      .catch(() => {})
      .finally(cargarPuertos);
  }, [show]);

  const buscar = async () => {
    setBuscando(true);
    setError(null);
    try {
      setPlacas(await cmaeApi.scanBle());
    } catch (e) {
      setPlacas(null);
      setError(e.message);
    } finally {
      setBuscando(false);
    }
  };

  const conectar = async (ev) => {
    ev?.preventDefault();
    let pedido = { origen: tab };
    if (tab === "ble") pedido.numero = Number(numero);
    else if (tab === "uart") pedido = { ...pedido, puerto };
    else pedido.formato = formato;

    setEnviando(true);
    setError(null);
    try {
      await cmaeApi.connect(pedido);
      onHide();
    } catch (e) {
      setError(e.message);
    } finally {
      setEnviando(false);
    }
  };

  const numeroOk = /^\d{1,3}$/.test(numero) && Number(numero) >= 1;
  const elegido = puertos?.find((p) => p.puerto === puerto);
  const listo = (tab === "ble" && numeroOk) || (tab === "uart" && !!puerto) || tab === "simulada";

  return (
    <Modal show={show} onHide={onHide} centered animation={false} backdropClassName="cfg-backdrop">
      <Form onSubmit={conectar}>
        <Modal.Header closeButton>
          <Modal.Title style={{ fontSize: 22 }}>Conectar la placa CMAE</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <Nav variant="pills" activeKey={tab} onSelect={(k) => (setTab(k), setError(null))} className="result-pills mb-3">
            {TABS.map(({ id, label, Icon }) => (
              <Nav.Item key={id}>
                <Nav.Link eventKey={id} className="d-inline-flex align-items-center gap-2">
                  <Icon size={15} /> {label}
                </Nav.Link>
              </Nav.Item>
            ))}
          </Nav>

          {tab === "ble" && (
            <>
              <Form.Group className="mb-3">
                <Form.Label>Número de la placa</Form.Label>
                <Form.Control type="number" min={1} max={999} value={numero} onChange={(e) => setNumero(e.target.value)}
                  placeholder="Por ejemplo, 5" autoFocus />
                <Form.Text>
                  {numeroOk ? <>Se buscará la placa <code>CMAE-{Number(numero)}-S3-N16R8</code>.</> : "Es el número que aparece en el nombre Bluetooth de la placa."}
                </Form.Text>
              </Form.Group>
              <Button variant="outline-secondary" size="sm" onClick={buscar} disabled={buscando} className="d-inline-flex align-items-center gap-2">
                {buscando ? <Spinner animation="border" size="sm" /> : <Search size={14} />}
                {buscando ? "Buscando (5 s)…" : "Buscar placas cercanas"}
              </Button>
              {placas && (
                <ListGroup className="mt-2">
                  {placas.length === 0 && <ListGroup.Item>No encontré ninguna placa CMAE encendida cerca.</ListGroup.Item>}
                  {placas.map((p) => (
                    <ListGroup.Item key={p.nombre} action type="button" active={String(p.numero) === numero} onClick={() => setNumero(String(p.numero))}>
                      {p.nombre}
                      {p.senal_dbm != null && <small className="float-end">{p.senal_dbm} dBm</small>}
                    </ListGroup.Item>
                  ))}
                </ListGroup>
              )}
            </>
          )}

          {tab === "uart" && (
            <>
              <Form.Group className="mb-3">
                <Form.Label>Puerto</Form.Label>
                <div className="d-flex gap-2">
                  <Form.Select value={puerto} onChange={(e) => setPuerto(e.target.value)}>
                    {!puertos?.length && <option value="">No hay puertos disponibles</option>}
                    {puertos?.map((p) => (
                      <option key={p.puerto} value={p.puerto}>
                        {p.puerto} — {p.descripcion}
                        {p.parece_placa ? " (parece la placa)" : ""}
                      </option>
                    ))}
                  </Form.Select>
                  <Button variant="outline-secondary" onClick={cargarPuertos} title="Volver a buscar puertos">
                    <RefreshCw size={15} />
                  </Button>
                </div>
                <Form.Text>
                  Conecta el cable a la entrada <strong>USB Serial Carga</strong> de la placa. No elijas el puerto del ESP32 del radar.
                </Form.Text>
              </Form.Group>
              {elegido?.es_debug && (
                <Alert variant="warning" className="py-2 mb-0">
                  Ese puerto es la entrada <strong>USB-Debug</strong>. Por ahí la placa no envía los datos de los sensores.
                </Alert>
              )}
            </>
          )}

          {tab === "simulada" && (
            <>
              <p className="mb-3">Una placa inventada, para probar el dashboard sin el hardware. Los valores no son reales.</p>
              <Form.Group>
                <Form.Label>Imitar la conexión por</Form.Label>
                <Form.Select value={formato} onChange={(e) => setFormato(e.target.value)} style={{ width: 220 }}>
                  <option value="BLE">Bluetooth</option>
                  <option value="UART">USB</option>
                </Form.Select>
              </Form.Group>
            </>
          )}

          {error && <Alert variant="danger" className="mt-3 mb-0 py-2">{error}</Alert>}
        </Modal.Body>
        <Modal.Footer>
          <Button variant="outline-secondary" onClick={onHide}>Cancelar</Button>
          <Button type="submit" variant="primary" disabled={!listo || enviando} className="d-inline-flex align-items-center gap-2">
            {enviando && <Spinner animation="border" size="sm" />} Conectar
          </Button>
        </Modal.Footer>
      </Form>
    </Modal>
  );
}
