// three.js의 형(type) 정보는 따로 받지 않았다(@types/three). 여기서 모듈 이름만 알려 주고, 그 안의 것은 any로 다룬다.
// 쓰는 곳은 console/Terrain3D.tsx 하나다.
declare module "three";
declare module "*.jsx";
declare module "three/examples/jsm/controls/OrbitControls.js";
declare module "three/examples/jsm/lines/Line2.js";
declare module "three/examples/jsm/lines/LineGeometry.js";
declare module "three/examples/jsm/lines/LineMaterial.js";
