import BpmnJS from 'bpmn-js';

const bpmnViewer = new BpmnJS({ container: '#bpmn-container' });

bpmnViewer.importXML(xmlData).then(() => {
  const canvas = bpmnViewer.get('canvas');
  canvas.zoom('fit-viewport'); // <-- this centers the diagram
});
