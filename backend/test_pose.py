import urllib.request, cv2, insightface
urllib.request.urlretrieve('https://raw.githubusercontent.com/deepinsight/insightface/master/sample-images/t1.jpg', 't1.jpg')
img = cv2.imread('t1.jpg')
app = insightface.app.FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
app.prepare(ctx_id=0, det_size=(640, 640))
faces = app.get(img)
print('POSE:', getattr(faces[0], 'pose', 'No pose attribute'))
